"""遊戲主流程（簡報 p.9）：
玩家輸入 → 安全檢查 → 人格提示詞＋劇本狀態 → LLM 生成 → 教練插話／評分覆盤

劇本狀態機：
- 每 TURNS_PER_STAGE 個玩家回合推進一階，最多推到第 4 階。
- 玩家表達要離開（關鍵字或第 5 階的清醒選項）→ 進入第 5 階。
- 第 5 階再聊 STAGE5_TURNS 回合 → 劇情結束，提示結算。
"""
from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import logging
import os
import re
import secrets
import time
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional

from . import coach, safety, scoring, achievements
from .llm import NPCRequest, fallback_output, generate_safe
from .personas import STAGE_TOTAL, Persona, render

TURNS_PER_STAGE = 3
STAGE5_TURNS = 2
HISTORY_TURNS = 12
TRUST_START = 40
MAX_TEXT = 300
MAX_AI_QA = 5
MAX_RESUMES = 3
REDACTED = "（此訊息觸發安全提示，原文未保存）"
RESUMABLE = ("pause", "too_painful")  # 這兩類觸發後可以按「回到遊戲」
TRUST_DELTA = {"brain": 10, "awake": -10, "neutral": 2}

_LEAVE = re.compile(
    r"分手|離開你|[不別]要?再聯[絡繫]|封鎖你|把你封鎖|到此為止|結束這段|我們結束|不想再跟你|再見了|"
    r"我走了|我要走了|我走啦|我先走|拜拜|掰掰")
_LEAVE_NEGATED = re.compile(
    r"(不想|不要|不會|別|不能|是不是想|是不是要|會不會|想不想|你想|你要)\s*(跟你)?(分手|離開你|結束)")
_LEAVE_FALSE = re.compile(r"我走了(?=[一二兩幾些圈步趟])")
# 撤回、玩笑、假設、疑問、第三人稱／過去式：不算玩家要離開
_LEAVE_VOID = re.compile(
    r"才怪|開玩笑|騙你的|唬你|的話|如果|假如|萬一|[嗎呢?？]\s*$|"
    r"(朋友|同事|同學|前任|前男友|前女友|閨蜜|室友|爸媽|爸爸|媽媽|姊姊|哥哥|他|她|他們|她們)[^，。,！!？?]{0,5}分手|"
    r"分手過|分過手|被分手")


def wants_leave(text: str) -> bool:
    """玩家是否表達要離開（Q18、Q57）：排除否定、疑問、假設、撤回與第三人稱。"""
    t = (text or "").strip()
    t = _LEAVE_NEGATED.sub("", t)
    t = _LEAVE_FALSE.sub("", t)
    if _LEAVE_VOID.search(t):
        return False
    return bool(_LEAVE.search(t))


def classify(text: str) -> str:
    """自由輸入的 kind 判定，規則集中在 scoring（Q3）。"""
    return scoring.resolve_kind(None, text)


def time_context(hour: Optional[int] = None) -> str:
    now = datetime.now()
    h = now.hour if hour is None else int(hour) % 24
    label = "深夜" if h < 6 else "早上" if h < 12 else "下午" if h < 18 else "晚上"
    return f"{label}（{h:02d}:{now.minute:02d}）"


class GameError(Exception):
    """可預期的玩法／請求錯誤。code 讓前端不必比對訊息字串（見 docs/api_contract.md）。"""

    def __init__(self, message: str = "", code: str = "bad_request"):
        super().__init__(message)
        self.code = code


log = logging.getLogger("game")
_CHOICE_ID = re.compile(r"^s([1-5])_(\d{1,2})$")


def dev_enabled() -> bool:
    return os.environ.get("GAME_DEV") == "1"


def _valid_token(token) -> Optional[str]:
    """token 長度驗證（Q64）：簽發的 token 為 32 字元，過短或過長一律視為沒帶。"""
    return token if isinstance(token, str) and 16 <= len(token) <= 256 else None


def _hash_token(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


_WARNED_DROPPED: set = set()


def _call_compat(fn, *args, **kw):
    """只傳 fn 實際接受的關鍵字參數，讓後端 A 的新介面上線前後都能跑。

    被略過的參數會 log 警告（每個函式／參數只警告一次），避免參數名稱不吻合時功能靜默失效。"""
    params = inspect.signature(fn).parameters
    if any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kw)
    dropped = [k for k in kw if k not in params]
    for k in dropped:
        key = (getattr(fn, "__module__", ""), getattr(fn, "__qualname__", repr(fn)), k)
        if key not in _WARNED_DROPPED:
            _WARNED_DROPPED.add(key)
            log.warning("_call_compat: %s does not accept keyword %r; argument dropped", key[1], k)
    return fn(*args, **{k: v for k, v in kw.items() if k in params})


def _clean_line(text: str) -> str:
    """歷史紀錄單行化並跳脫標籤，玩家文字不能偽造 <history> 或多行系統段落（Q7）。"""
    text = "".join(" " if (ord(c) < 32 or c in "\u2028\u2029\x85") else c for c in str(text))
    # 移除零寬／雙向控制字元（Cf），並把冒號換成小冒號，讓玩家文字不能在同一行偽造「角色：」發言（Q45）
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    text = text.replace("：", "﹕").replace(":", "﹕")
    return text.replace("<", "＜").replace(">", "＞").strip()


class Game:
    def __init__(self, personas: Dict[str, Persona], store, llm):
        self.personas = personas
        self.store = store
        self.llm = llm

    # ---------- helpers ----------
    def _persona(self, pid: str) -> Persona:
        if pid not in self.personas:
            raise GameError(f"unknown persona: {pid}")
        return self.personas[pid]

    @staticmethod
    def _new_state(persona: Persona, gender: str) -> dict:
        return {
            "persona_id": persona.id, "gender": gender,
            "npc_name": persona.npc_name(gender),
            "stage": 1, "trust": TRUST_START, "player_turns": 0, "stage5_turns": 0,
            "ended": False, "safety": None, "messages": [], "used_lines": [],
            "brain_count": 0, "awake_count": 0, "money_events": [],
            "created_at": time.time(), "next_id": 1,
        }

    @staticmethod
    def _add(state: dict, role: str, text: str, **extra) -> dict:
        msg = {"id": state["next_id"], "role": role, "text": text, "ts": time.time()}
        msg.update(extra)
        state["next_id"] += 1
        state["messages"].append(msg)
        return msg

    def _choices(self, persona: Persona, state: dict, stage=None) -> List[dict]:
        return persona.choices(state["stage"] if stage is None else stage,
                               seed=f"{state['created_at']}")

    def _history_text(self, state: dict, skip_last_player: bool = False) -> str:
        convo = [m for m in state["messages"] if m["role"] in ("npc", "player")]
        if skip_last_player and convo and convo[-1]["role"] == "player":
            convo = convo[:-1]  # 最新一句另外當 user message 傳給 LLM，避免重複
        rows = []
        for m in convo[-HISTORY_TURNS * 2:]:
            who = _clean_line(state["npc_name"]) if m["role"] == "npc" else "玩家"
            rows.append(f"{who}：{_clean_line(m['text'])}")
        body = "\n".join(rows) or "（尚無對話，這是第一則訊息）"
        return f"<history>\n{body}\n</history>"

    def build_prompt(self, persona: Persona, state: dict, hour: Optional[int] = None,
                     skip_last_player: bool = False) -> str:
        body = render(persona.prompt_template, {
            "npc_name": state["npc_name"],
            "npc_age": persona.cfg["age"],
            "npc_gender": "男性" if state["gender"] == "男" else "女性",
            "time_context": time_context(hour),
            "stage": state["stage"],
            "trust_score": state["trust"],
            "recent_history": self._history_text(state, skip_last_player),
        })
        rule = ""
        if skip_last_player:  # 有玩家新訊息時：先回應玩家剛說的話，再推進劇情
            rule = ("\n<reply_rule>\n先直接回應玩家最新這句話（回答他的問題、接他說的內容與情緒），"
                    "再依目前階段自然地推進劇情；不要無視玩家的話、不要自顧自重複上一段台詞。\n</reply_rule>")
        return body + self._player_info_block(state.get("player_info")) + rule

    _AGE_RE = re.compile(r"我(?:今年)?\s*(\d{2})\s*歲")

    @classmethod
    def _player_info(cls, prof: dict) -> dict:
        """跨人格共用的玩家基本資訊（暱稱、玩家自己說過的年齡）。換對象時帶入 prompt，NPC 不必重問。"""
        info = {}
        if prof.get("nickname"):
            info["nickname"] = prof["nickname"]
        for st in prof.get("sessions", {}).values():
            for m in st.get("messages", []):
                if m.get("role") == "player":
                    hit = cls._AGE_RE.search(m.get("text", ""))
                    if hit and 18 <= int(hit.group(1)) <= 99:
                        info["age"] = int(hit.group(1))
        known = {k: v for k, v in info.items()}
        others = [st for st in prof.get("sessions", {}).values() if st.get("player_turns", 0) > 0]
        if known or others:
            info["met_others"] = bool(others)
        return info

    @staticmethod
    def _player_info_block(info: Optional[dict]) -> str:
        if not info:
            return ""
        rows = []
        if info.get("nickname"):
            rows.append(f"玩家的暱稱：{_clean_line(info['nickname'])}")
        if info.get("age"):
            rows.append(f"玩家自己說過的年齡：{info['age']} 歲")
        if info.get("met_others"):
            rows.append("玩家已經在這個遊戲裡聊過別人，不是第一次聊天。")
        if not rows:
            return ""
        rows.append("以上是玩家已提供的基本資訊：不要再重新詢問或要求自我介紹，自然地沿用即可。")
        return "\n<player_info>\n" + "\n".join(rows) + "\n</player_info>"

    def _npc_turn(self, persona: Persona, state: dict, player_text: str,
                  hour: Optional[int]) -> Optional[dict]:
        req = NPCRequest(persona, state["gender"], state["stage"], state["trust"],
                         self.build_prompt(persona, state, hour, bool(player_text)), player_text,
                         state["used_lines"], seed=state.get("created_at"))
        out = generate_safe(self.llm, req)  # 失敗重試一次，仍失敗用 fallback，不丟回合
        if out.get("break_character"):
            hit = safety.assess(player_text) if player_text else None
            if hit and hit["category"] == "ai_identity":  # 玩家真的在問 AI 身分：不終局、不計分
                self._add(state, "system", out.get("reply") or "", safety=safety.response(
                    "ai_identity", out.get("reply", ""), severity=hit["severity"]))
                return None
            # Q31：玩家原文沒有終局級的 safety 觸發 → 視為模型拒答／跳戲（技術問題）：
            # 不終局、不顯示熱線，用不帶紅旗的安全 fallback 續局。終局只由玩家原文的 safety 決定。
            log.warning("model break_character without player safety hit (persona=%s stage=%s); using fallback",
                        persona.id, state["stage"])
            out = fallback_output(req)
        state["used_lines"].append(out.get("_line", out["reply"]))
        return self._add(state, "npc", out["reply"], red_flags=out.get("red_flags", []),
                         flagged=False, stage=state["stage"],
                         **({"fallback": True} if out.get("_fallback") else {}))

    def _advance(self, state: dict, leave: bool) -> None:
        if state["stage"] == 5:
            state["stage5_turns"] += 1
            if state["stage5_turns"] >= STAGE5_TURNS:
                state["ended"] = True
            return
        if leave:
            state["stage"] = 5
            return
        state["stage"] = min(4, 1 + state["player_turns"] // TURNS_PER_STAGE)

    # ---------- views ----------
    def public_state(self, persona: Persona, state: dict, reveal: bool = False) -> dict:
        reveal = bool(reveal) and dev_enabled()  # Q13：reveal 只在 GAME_DEV=1 有效
        msgs = []
        for m in state["messages"]:
            v = {k: m[k] for k in ("id", "role", "text") if k in m}
            if m["role"] == "npc":
                v["flagged"] = m.get("flagged", False)
                if m.get("flagged") or reveal or state.get("reviewed") or state["safety"]:
                    v["red_flags"] = [{"code": f, "meaning": persona.flag_meaning(f)}
                                      for f in m.get("red_flags", [])]
            if m["role"] == "coach":
                # Q67：praise 與 neutral 對外一律 neutral，tone 本身不能洩漏「這句有沒有紅旗」
                v["tone"] = "neutral" if m.get("tone") in ("praise", "neutral") else m.get("tone")
                v["severity"] = m.get("severity", coach.DEFAULT_SEVERITY)
            if m["role"] == "player":
                v["kind"] = m.get("kind")
            if m["role"] == "meta_player":  # 不計分的提問（例如問對方是不是 AI），對前端顯示成玩家訊息
                v["role"] = "player"
                v["meta"] = True
            if m.get("safety"):
                v["safety"] = m["safety"]
            msgs.append(v)
        choices = [] if state["ended"] else [
            {"id": f"s{state['stage']}_{i}", "text": c["text"]}
            for i, c in enumerate(self._choices(persona, state))
        ]
        npc_flagged = [m for m in state["messages"] if m["role"] == "npc" and m.get("flagged")]
        reviewed = bool(state.get("reviewed"))
        if reviewed or state["safety"]:
            phase = "locked"          # 已結算或被安全機制終止：不能再標旗
        elif state["ended"]:
            phase = "final_check"     # 自然結束、尚未結算：可最後補標，再按結算
        else:
            phase = "playing"
        return {
            "reviewed": reviewed, "phase": phase,
            "persona_id": persona.id, "npc_name": state["npc_name"], "gender": state["gender"],
            "can_resume": bool(state["safety"] and state["safety"].get("category") in RESUMABLE),
            "stage": state["stage"], "stage_total": STAGE_TOTAL,
            "flags_reported": len(npc_flagged),
            "flags_caught_so_far": sum(1 for m in npc_flagged if m.get("red_flags")),
            "stage_name": persona.stage_names.get(state["stage"], ""),
            "trust": state["trust"], "ended": state["ended"], "safety": state["safety"],
            "messages": msgs, "choices": choices,
            "money_lost": sum(e["amount"] for e in state["money_events"]),
            "llm": self.llm.name,
        }

    def profile_summary(self, player_id: str) -> dict:
        with self.store.lock(player_id):
            prof = self.store.load(player_id)
        sessions = {}
        for pid, st in prof["sessions"].items():
            sessions[pid] = {"stage": st["stage"], "ended": st["ended"],
                             "turns": st["player_turns"], "npc_name": st["npc_name"]}
        return {"player_id": player_id, "nickname": prof.get("nickname", ""),
                "sessions": sessions, "reviews": prof["reviews"][-10:],
                "prefs": prof.get("prefs", {}), "consent": prof.get("consent")}

    # ---------- actions（每個動作用該玩家的鎖包住整個 load-modify-save，Q5）----------
    def set_nickname(self, player_id: str, nickname: str) -> None:
        if not isinstance(nickname, str):
            raise GameError("nickname must be a string")
        with self.store.lock(player_id):
            prof = self.store.load(player_id)
            prof["nickname"] = nickname.strip()[:20]
            self.store.save(prof)

    PREF_KEYS = {"severity": (1, 2, 3), "theme": ("light", "dark", "auto"),
                 "mute_coach": (True, False), "feel_uncomfortable": (True, False)}
    _BOOL_PREFS = ("mute_coach", "feel_uncomfortable")

    def set_prefs(self, player_id: str, prefs: dict) -> dict:
        if not isinstance(prefs, dict):
            raise GameError("prefs must be an object")
        with self.store.lock(player_id):
            prof = self.store.load(player_id)
            for k, v in prefs.items():
                if k not in self.PREF_KEYS:
                    raise GameError(f"invalid pref: {k}")
                if k in self._BOOL_PREFS:
                    ok = isinstance(v, bool)
                else:
                    ok = not isinstance(v, bool) and isinstance(v, (int, str)) and v in self.PREF_KEYS[k]
                if not ok:
                    raise GameError(f"invalid pref: {k}")
                prof["prefs"][k] = v
            self.store.save(prof)
            return prof["prefs"]

    _CONSENT_VERSION = re.compile(r"^[A-Za-z0-9._\-]{1,32}$")

    def set_consent(self, player_id: str, version, accepted=True) -> dict:
        """只記錄、不強制：start/send 不檢查同意狀態。"""
        if not isinstance(version, str) or not self._CONSENT_VERSION.match(version):
            raise GameError("invalid consent version")
        if not isinstance(accepted, bool):
            raise GameError("accepted must be a boolean")
        with self.store.lock(player_id):
            prof = self.store.load(player_id)
            prof["consent"] = {"version": version, "accepted": accepted, "ts": time.time()}
            self.store.save(prof)
            return prof["consent"]

    # ---------- 玩家憑證（Q36 / Q12）----------
    def _auth_enabled(self) -> bool:
        return os.environ.get("GAME_REQUIRE_TOKEN", "1") != "0"

    def authorize(self, player_id: str, token: Optional[str], create: bool) -> Optional[str]:
        """檢查憑證。回傳新簽發的 token（呼叫端放進回應），沒簽發回 None。

        所有授權失敗一律同一種回應 GameError("invalid or missing token", "unauthorized")，
        不區分「玩家不存在／沒帶 token／token 錯」，避免存在性洩漏（Q52）。唯一例外是建檔型路由
        （create=True）對「不存在的玩家」會直接建立並簽發。

        - 已有 token_hash：token 必須相符。
        - 沒有 token_hash 的既有存檔（舊存檔）：預設拒絕（Q50）；只有 GAME_ALLOW_LEGACY_CLAIM=1
          且 create=True 時允許認領，否則只能由管理者遷移（migrate_legacy）或刪除。
        - 不存在：create=True 時建立（受總量上限限制）；create=False 一律 unauthorized。
        呼叫端須已持有該玩家的鎖。
        """
        if not self._auth_enabled():
            return None
        token = _valid_token(token)
        exists = self.store.exists(player_id)
        prof = self.store.load(player_id)
        h = prof.get("token_hash")
        if h:
            if not (token and hmac.compare_digest(h, _hash_token(token))):
                raise GameError("invalid or missing token", "unauthorized")
            return None
        if exists and not (create and os.environ.get("GAME_ALLOW_LEGACY_CLAIM") == "1"):
            raise GameError("invalid or missing token", "unauthorized")
        if not create:
            raise GameError("invalid or missing token", "unauthorized")
        if not exists:
            cap = int(os.environ.get("GAME_MAX_PLAYERS", "2000"))
            if self.store.count_players() >= cap:
                raise GameError("player quota exceeded", "quota_exceeded")
        new = secrets.token_urlsafe(24)
        prof["token_hash"] = _hash_token(new)
        self.store.save(prof)
        return new

    def check_read(self, player_id: str, token: Optional[str]) -> None:
        """GET /api/profile：不存在、舊存檔、token 錯都回同一種 unauthorized。"""
        if not self._auth_enabled():
            return
        token = _valid_token(token)
        h = self.store.load(player_id).get("token_hash") if self.store.exists(player_id) else None
        if not (h and token and hmac.compare_digest(h, _hash_token(token))):
            raise GameError("invalid or missing token", "unauthorized")

    def migrate_legacy(self, player_id: str) -> dict:
        """管理者遷移：替既有的無 token 舊存檔簽發 token（交付給原主）。"""
        with self.store.lock(player_id):
            if not self.store.exists(player_id):
                raise GameError("no such profile", "not_found")
            prof = self.store.load(player_id)
            if prof.get("token_hash"):
                raise GameError("profile already has a token", "bad_request")
            new = secrets.token_urlsafe(24)
            prof["token_hash"] = _hash_token(new)
            self.store.save(prof)
            return {"ok": True, "token": new}

    @staticmethod
    def install_safety_classifier(classifier) -> bool:
        """接線（Q48）：把第二道 safety 分類器注入 safety.set_classifier。
        後端 A 的介面尚未提供時回 False（不報錯）。classifier(text) -> assess() 同形狀的 dict 或 None。"""
        setter = getattr(safety, "set_classifier", None)
        if setter is None:
            log.warning("safety.set_classifier not available; classifier not installed")
            return False
        setter(classifier)
        return True

    def delete_profile(self, player_id: str) -> dict:
        """刪除我的資料（Q10）：存檔、暱稱、對話、成績、被隔離的損毀檔全部移除。"""
        with self.store.lock(player_id):
            return {"ok": True, "deleted": self.store.delete(player_id)}

    def start(self, player_id: str, persona_id: str, gender: Optional[str] = None,
              hour: Optional[int] = None, reveal: bool = False) -> dict:
        persona = self._persona(persona_id)
        with self.store.lock(player_id):
            prof = self.store.load(player_id)
            state = prof["sessions"].get(persona_id)
            if state is None:  # 第一次見面才開新局；否則接續存檔
                gender = gender if gender in ("男", "女") else persona.cfg["default_gender"]
                state = self._new_state(persona, gender)
                state["player_info"] = self._player_info(prof)
                self._npc_turn(persona, state, "", hour)
                prof["sessions"][persona_id] = state
                self.store.save(prof)
            return self.public_state(persona, state, reveal)

    def reset(self, player_id: str, persona_id: str) -> None:
        with self.store.lock(player_id):
            prof = self.store.load(player_id)
            prof["sessions"].pop(persona_id, None)
            self.store.save(prof)

    def _resolve_choice(self, persona: Persona, state: dict, choice_id: str) -> dict:
        """choice_id 必須是「當前階段」的合法索引（Q23）：不可跨階段、不可負索引。"""
        m = _CHOICE_ID.match(choice_id) if isinstance(choice_id, str) else None
        if not m or int(m.group(1)) != state["stage"]:
            raise GameError("invalid choice", "invalid_choice")
        options = self._choices(persona, state)
        idx = int(m.group(2))
        if idx >= len(options):
            raise GameError("invalid choice", "invalid_choice")
        return options[idx]

    def send(self, player_id: str, persona_id: str, text: str = "", choice_id: str = "",
             severity: Optional[int] = None, hour: Optional[int] = None, reveal: bool = False) -> dict:
        persona = self._persona(persona_id)
        if text is not None and not isinstance(text, str):
            raise GameError("text must be a string")
        if choice_id is not None and not isinstance(choice_id, str):
            raise GameError("choice_id must be a string")
        severity = severity if severity in (1, 2, 3) else coach.DEFAULT_SEVERITY
        with self.store.lock(player_id):
            return self._send_locked(persona, player_id, text or "", choice_id or "", severity,
                                     hour, reveal)

    def _send_locked(self, persona, player_id, text, choice_id, severity, hour, reveal) -> dict:
        prof = self.store.load(player_id)
        state = prof["sessions"].get(persona.id)
        if state is None:
            raise GameError("session not started", "not_started")
        if state["ended"]:
            raise GameError("session ended", "ended")
        state["player_info"] = self._player_info(prof)  # 暱稱可能中途才改，每回合刷新

        money, chosen_kind, leave, choice_key = 0, None, False, None
        if choice_id:
            choice = self._resolve_choice(persona, state, choice_id)
            text, chosen_kind = choice["text"], choice["kind"]
            money = choice.get("money", 0)
            choice_key = f"{persona.id}:{choice_id}"
            # 同一個金額選項每局只計一次，避免連點灌金額
            used = state.setdefault("used_choices", [])
            if money and choice_key in used:
                money = 0
            elif money:
                used.append(choice_key)
            leave = chosen_kind == "awake" and state["stage"] >= 4 and persona.id != "scammer"
        text = text.strip()[:MAX_TEXT]
        if not text:
            raise GameError("empty message")

        last_npc = next((m for m in reversed(state["messages"]) if m["role"] == "npc"), None)
        source = "choice" if chosen_kind else "text"
        kind = "neutral" if chosen_kind == "neutral" else scoring.resolve_kind(chosen_kind, text)
        if not choice_id and kind == "brain":  # 自由輸入也抽金額
            money = scoring.money_in_text(text)

        hit = safety.assess(text)
        notice = None
        if hit:
            resp = safety.response(hit["category"], severity=hit["severity"])
            if hit["category"] == "ai_identity":
                # 如實回答、不終局、不計分、不呼叫 LLM。每局最多記錄 MAX_AI_QA 次問答（Q43），
                # 超過後只回傳提示、不再增加訊息與存檔大小。
                state["ai_identity_count"] = state.get("ai_identity_count", 0) + 1
                if state["ai_identity_count"] <= MAX_AI_QA:
                    self._add(state, "meta_player", text)
                    self._add(state, "system", resp["message"], safety=resp)
                self.store.save(prof)
                out = self.public_state(persona, state, reveal)
                out["notice"] = resp
                return out
            # Q42：觸發安全規則的原文一律不入庫，只留類別與時間
            prof.setdefault("safety_events", []).append(
                {"ts": time.time(), "category": hit["category"], "severity": hit["severity"],
                 "persona_id": persona.id})
            del prof["safety_events"][:-50]
            if hit["ends_session"]:
                if hit["category"] == "pause":
                    self._add(state, "meta_player", REDACTED)
                state["ended"] = True
                state["safety"] = resp
                self.store.save(prof)
                return self.public_state(persona, state, reveal)
            notice = resp  # 低風險降級：提醒＋資源，繼續遊戲
        # 送給 LLM 的仍是原文；存檔裡的玩家訊息若觸發過安全規則則只留遮蔽字串
        self._add(state, "player", REDACTED if hit else text, kind=kind, source=source)
        if notice:
            self._add(state, "system", notice["message"], safety=notice)

        state["player_turns"] += 1
        if kind in ("brain", "awake"):  # neutral 不計入戀愛腦／清醒次數
            state[f"{kind}_count"] += 1
            state.setdefault("kind_counts", {}).setdefault(source, {}).setdefault(kind, 0)
            state["kind_counts"][source][kind] += 1
        state["trust"] = max(0, min(100, state["trust"] + TRUST_DELTA[kind]))
        if money:
            state["money_events"].append({"amount": money, "stage": state["stage"],
                                          "source": source})

        prefs = prof.get("prefs", {})
        if prefs.get("feel_uncomfortable"):
            severity = 1  # 玩家標示「我不舒服」：教練一律溫柔
        tip = _call_compat(coach.interject, persona, state["npc_name"], last_npc, text, kind,
                           severity, money, state["player_turns"],
                           has_red_flag=None if last_npc is None else bool(last_npc.get("red_flags")))
        if tip and not prefs.get("mute_coach"):  # 靜音只是不產生教練訊息，計分不受影響
            self._add(state, "coach", tip["text"], tone=tip["tone"],
                      severity=tip.get("severity", severity))

        leave = leave or wants_leave(text) or (
            persona.id == "scammer" and chosen_kind == "awake" and state["stage"] >= 4)
        self._advance(state, leave)
        if not state["ended"] or state["stage"] == 5:
            npc = self._npc_turn(persona, state, text, hour)
            if npc is not None:
                npc["reply_to_kind"] = kind
        if state["ended"] and not state["safety"]:
            self._add(state, "system", "劇情結束。按「結算」看你的清醒分數與覆盤。")
        self.store.save(prof)
        out = self.public_state(persona, state, reveal)
        if notice:
            out["notice"] = notice
        return out

    def resume(self, player_id: str, persona_id: str, reveal: bool = False,
               confirm: bool = False) -> dict:
        """pause / too_painful 觸發後，玩家按「回到遊戲」：進度保留，局繼續。"""
        persona = self._persona(persona_id)
        with self.store.lock(player_id):
            prof = self.store.load(player_id)
            state = prof["sessions"].get(persona_id)
            if state is None:
                raise GameError("session not started", "not_started")
            sf = state.get("safety")
            if not (state["ended"] and sf and sf.get("category") in RESUMABLE):
                raise GameError("session cannot be resumed", "not_resumable")
            if state.get("resume_count", 0) >= MAX_RESUMES:
                raise GameError("too many resumes in this session; please reset or take a break", "resume_limit")
            if sf["category"] == "too_painful":  # Q35：需要確認，且短時間內重複觸發不可立即回去
                if confirm is not True:
                    raise GameError("confirm required: pass confirm=true after the player says they are okay",
                                    "confirm_required")
                cooldown = float(os.environ.get("GAME_RESUME_COOLDOWN", "600"))
                now = time.time()
                recent = [e for e in prof.get("safety_events", []) if e["category"] == "too_painful"
                          and now - e["ts"] < cooldown]
                if len(recent) >= 2:
                    raise GameError("cooldown: please take a rest before coming back", "cooldown")
            state["resume_count"] = state.get("resume_count", 0) + 1
            state["ended"] = False
            state["safety"] = None
            self._add(state, "system", "歡迎回來，我們從剛剛的地方繼續。")
            self.store.save(prof)
            return self.public_state(persona, state, reveal)

    def flag(self, player_id: str, persona_id: str, msg_id: int) -> dict:
        persona = self._persona(persona_id)
        if isinstance(msg_id, bool) or not isinstance(msg_id, int):
            raise GameError("msg_id must be an integer")
        with self.store.lock(player_id):
            prof = self.store.load(player_id)
            state = prof["sessions"].get(persona_id)
            if state is None:
                raise GameError("session not started", "not_started")
            # Q47 寬限：劇情自然結束後、結算（review）之前仍可補標（答案在結算前不公開，
            # 所以不構成偷看）；結算後、或被安全機制終止的局才鎖定。
            if state.get("reviewed") or state["safety"]:
                raise GameError("session ended; flags are locked", "locked")
            msg = next((m for m in state["messages"] if m["id"] == msg_id and m["role"] == "npc"), None)
            if msg is None:
                raise GameError("message not found")
            if not msg.get("flagged"):
                msg["flagged"] = True
                self.store.save(prof)
            flags = msg.get("red_flags", [])
            return {
                "msg_id": msg_id,
                "correct": bool(flags),
                "red_flags": [{"code": f, "meaning": persona.flag_meaning(f)} for f in flags],
                "flags_caught_so_far": sum(1 for m in state["messages"]
                                           if m["role"] == "npc" and m.get("flagged") and m.get("red_flags")),
                "flags_reported": sum(1 for m in state["messages"]
                                      if m["role"] == "npc" and m.get("flagged")),
            }

    def review(self, player_id: str, persona_id: str, severity: Optional[int] = None,
               finish: bool = False) -> dict:
        """結算。局中直接呼叫會被拒（Q21，避免偷看答案）；finish=True 代表玩家主動放棄／結束這局。"""
        persona = self._persona(persona_id)
        severity = severity if severity in (1, 2, 3) else coach.DEFAULT_SEVERITY
        with self.store.lock(player_id):
            prof = self.store.load(player_id)
            state = prof["sessions"].get(persona_id)
            if state is None:
                raise GameError("session not started", "not_started")
            natural_end = bool(state["ended"] and not state.get("safety")
                               and state.get("stage") == 5 and state.get("stage5_turns", 0) >= STAGE5_TURNS)
            if not state["ended"]:
                if not finish:
                    raise GameError("session not finished; pass finish=true to end it and see the review", "not_finished")
                state["ended"] = True  # 結束後 flag 即鎖定
            scores = _call_compat(scoring.compute, state)
            past = [r for r in prof["reviews"] if r.get("session_at") != state["created_at"]]
            report = coach.review(persona, state["npc_name"], state, scores, severity, past)
            self._enrich_items(report, state)
            if not state.get("reviewed"):  # 同一局重複按結算只記一次成績
                prof["reviews"].append({
                    "persona_id": persona.id, "persona_title": persona.title,
                    "awake_score": scores["awake_score"], "fooled_index": scores["fooled_index"],
                    "recall": scores["recall"], "ts": time.time(), "session_at": state["created_at"],
                    "achievement_stats": achievements.review_evidence(state, scores, natural_end),
                })
                state["reviewed"] = True
            earned = achievements.sync(prof)
            self.store.save(prof)
            return {"scores": scores, "coach": report, "achievements": earned}

    @staticmethod
    def _enrich_items(report: dict, state: dict) -> None:
        """逐句覆盤補上 msg_id、stage、player_reply（玩家當時對這句 NPC 訊息的回覆）。"""
        msgs = state["messages"]
        cursor = 0
        for item in report.get("items", []):
            for j in range(cursor, len(msgs)):
                m = msgs[j]
                if m["role"] == "npc" and m["text"] == item.get("text"):
                    cursor = j + 1
                    reply = next((x for x in msgs[j + 1:] if x["role"] in ("player", "npc")), None)
                    item.setdefault("msg_id", m["id"])
                    item.setdefault("stage", m.get("stage"))
                    item.setdefault("player_reply", reply["text"] if reply and reply["role"] == "player" else None)
                    break
