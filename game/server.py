"""醒醒吧！戀愛腦 —— 本機測試伺服器（只用 Python 標準函式庫）。

    python3 server.py              # mock AI，開 http://localhost:8000
    GAME_LLM=claude python3 server.py   # 之後接 Claude API

API（全部 JSON）：
    GET  /api/personas
    GET  /api/profile?player=ID
    POST /api/nickname   {player, nickname}
    POST /api/start      {player, persona, gender?, hour?, reveal?}
    POST /api/message    {player, persona, text | choice_id, severity, hour?, reveal?}
    POST /api/flag       {player, persona, msg_id}
    POST /api/review     {player, persona, severity}
    POST /api/reset      {player, persona}
    POST /api/resume     {player, persona}   pause / too_painful 之後回到遊戲
    POST /api/consent    {player, version, accepted?}   只記錄，不強制
    POST /api/prefs      {player, prefs:{severity?, theme?}}
    GET  /api/resources
    DELETE /api/profile?player=ID   或 POST /api/profile/delete {player}   刪除我的全部資料
    GET  /api/prompt?player=ID&persona=X   （僅 GAME_DEV=1：看實際送給 LLM 的 system prompt）

POST 一律要求 Content-Type: application/json 且 body 為 JSON 物件，否則 400 JSON。
review 局中需帶 finish:true（主動結束這局）；reveal / hour 只在 GAME_DEV=1 有效。
"""
from __future__ import annotations

import collections
import hashlib
import hmac
import json
import logging
import re
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

GAME_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(GAME_DIR))

from engine import coach, safety, quiz, achievements  # noqa: E402
from engine.game import Game, GameError, dev_enabled  # noqa: E402
from engine.llm import get_llm  # noqa: E402
from engine.personas import PersonaLoadError, load_personas  # noqa: E402
from engine.store import Store  # noqa: E402

STATIC_DIR = GAME_DIR / "static"
log = logging.getLogger("game.server")


def build_game(save_dir: Path = GAME_DIR / "saves", llm=None) -> Game:
    return Game(load_personas(), Store(save_dir), llm or get_llm())


MAX_BODY = 32 * 1024


class BadRequest(Exception):
    def __init__(self, message: str = "", code: str = "bad_request"):
        super().__init__(message)
        self.code = code


STATUS_BY_CODE = {"unauthorized": 401, "forbidden": 403, "not_found": 404,
                  "quota_exceeded": 429, "rate_limited": 429}
CREATE_ROUTES = {"/api/start", "/api/nickname", "/api/consent", "/api/prefs"}
_rate_lock = threading.Lock()
_rate: dict = {}


def rate_limit(key: str, env: str = "GAME_RATE_PER_MIN", default: int = 60,
               window: float = 60.0) -> None:
    """滑動視窗限流。key 例如 "p:<玩家ID>"、"ip:<來源IP>"。limit<=0 代表不限。"""
    limit = int(os.environ.get(env, str(default)))
    if limit <= 0:
        return
    now = time.time()
    with _rate_lock:
        q = _rate.setdefault(key, collections.deque())
        window_s = window
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            raise BadRequest("too many requests", "rate_limited")
        q.append(now)
        if len(_rate) > 5000:  # 避免字典無限成長
            for k in [k for k, v in _rate.items() if not v or now - v[-1] > 3600]:
                _rate.pop(k, None)


def auth_blocked(ip: str, pid: str) -> None:
    """Q64：錯誤憑證嘗試節流。每 IP、每 ID 在滑動視窗內失敗太多次 → 429（不再檢查憑證）。"""
    now = time.time()
    window = float(os.environ.get("GAME_AUTH_FAIL_WINDOW", "60"))
    for key, env, default in ((f"fail-ip:{ip}", "GAME_AUTH_FAIL_PER_IP", 30),
                              (f"fail-id:{pid}|{ip}", "GAME_AUTH_FAIL_PER_ID", 10)):
        limit = int(os.environ.get(env, str(default)))
        if limit <= 0:
            continue
        with _rate_lock:
            q = _rate.get(key)
            if q is None:
                continue
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                raise BadRequest("too many failed attempts; try again later", "rate_limited")


def auth_failed(ip: str, pid: str) -> None:
    now = time.time()
    with _rate_lock:
        for key in (f"fail-ip:{ip}", f"fail-id:{pid}|{ip}"):
            _rate.setdefault(key, collections.deque()).append(now)


def hash_id(pid: str) -> str:
    return hashlib.sha256(pid.encode("utf-8")).hexdigest()[:8]


def error_body(e: Exception):
    code = getattr(e, "code", "bad_request")
    return {"error": str(e), "code": code}, STATUS_BY_CODE.get(code, 400)


def _str(b: dict, key: str, required: bool = True, default: str = "") -> str:
    v = b.get(key, None)
    if v is None or v == "":
        if required:
            raise BadRequest(f"missing field: {key}")
        return default
    if not isinstance(v, str):
        raise BadRequest(f"{key} must be a string")
    return v


def _int(v, name: str, lo: int, hi: int, default=None, clamp: bool = False):
    if v is None or v == "":
        return default
    if isinstance(v, bool) or not isinstance(v, (int, str)):
        raise BadRequest(f"{name} must be an integer")
    try:
        n = int(v)
    except ValueError:
        raise BadRequest(f"{name} must be an integer")
    if clamp:
        return max(lo, min(hi, n))
    if not lo <= n <= hi:
        raise BadRequest(f"{name} out of range")
    return n


def _player(b: dict) -> str:
    """玩家 ID：格式由 Store 白名單把關；長度下限預設 8（GAME_MIN_ID_LEN，Q12）。"""
    pid = _str(b, "player")
    if len(pid) < int(os.environ.get("GAME_MIN_ID_LEN", "8")):
        raise BadRequest("player id too short")
    return pid


def _persona(game, b: dict) -> str:
    pid = _str(b, "persona")
    if pid not in game.personas:
        raise BadRequest(f"unknown persona: {pid}")
    return pid


def make_handler(game: Game):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(STATIC_DIR), **kw)

        def log_message(self, fmt, *args):
            # Q69：存取 log 不記 query string（會含玩家 ID）
            if os.environ.get("GAME_QUIET") != "1":
                msg = (fmt % args) if args else fmt
                msg = re.sub(r"\?\S*", "?…", msg)
                sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), msg))

        def _json(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                raise BadRequest("Content-Type must be application/json")
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise BadRequest("bad Content-Length")
            if n < 0:
                raise BadRequest("bad Content-Length")
            if n > MAX_BODY:
                raise BadRequest("body too large")
            raw = self.rfile.read(n) if n else b""
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                raise BadRequest("bad json")
            if not isinstance(data, dict):
                raise BadRequest("body must be a JSON object")
            return data

        def _handle(self, fn):
            try:
                self._json(fn())
            except (GameError, BadRequest, ValueError) as e:
                self._json(*error_body(e))
            except Exception:  # LLM 連線錯誤等：細節只進 log，不回傳給客戶端
                log.exception("unhandled error")
                self._json({"error": "server error", "code": "server_error"}, 500)

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/api/achievements/catalog":
                return self._handle(lambda: achievements.sync({}))
            if url.path == "/api/personas":
                return self._handle(lambda: [p.public() for p in game.personas.values()])
            if url.path == "/api/resources":
                return self._handle(lambda: {"resources": safety.RESOURCES, "dev": dev_enabled()})
            if url.path == "/api/profile":
                def profile():
                    pid = _player(q)
                    ip = self.client_address[0]
                    auth_blocked(ip, pid)
                    try:
                        game.check_read(pid, self.headers.get("X-Player-Token"))
                    except GameError as e:
                        if e.code == "unauthorized":
                            auth_failed(ip, pid)
                        raise
                    return game.profile_summary(pid)
                return self._handle(profile)
            if url.path == "/api/prompt":
                if not dev_enabled():
                    return self._json({"error": "not found", "code": "not_found"}, 404)

                def prompt():
                    persona = game.personas.get(_str(q, "persona"))
                    if persona is None:
                        raise BadRequest("unknown persona")
                    pid = _str(q, "player")
                    with game.store.lock(pid):
                        sess = game.store.load(pid)["sessions"].get(persona.id)
                    if sess is None:
                        raise BadRequest("session not started")
                    return {"prompt": game.build_prompt(persona, sess)}
                return self._handle(prompt)
            if url.path.startswith("/api/"):
                return self._json({"error": "not found", "code": "not_found"}, 404)
            return super().do_GET()

        def do_DELETE(self):
            url = urlparse(self.path)
            if url.path == "/api/profile":
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                return self._handle(lambda: self._guarded(
                    "/api/profile", _player(q), self.headers.get("X-Player-Token"),
                    lambda: game.delete_profile(_player(q))))
            return self._json({"error": "not found", "code": "not_found"}, 404)

        def _is_admin(self) -> bool:
            admin = os.environ.get("GAME_ADMIN_TOKEN")
            if not admin:
                return False
            given = self.headers.get("X-Admin-Token") or ""
            try:  # header 可能含非 ASCII：一律用 bytes 比對，不可 500（Q53）
                return hmac.compare_digest(given.encode("utf-8"), admin.encode("utf-8"))
            except Exception:
                return False

        def _guarded(self, path, pid, token, fn):
            """速率限制 → 憑證檢查（必要時簽發 token）→ 執行 → 回應附 token。整段在該玩家的鎖內。"""
            ip = self.client_address[0]
            rate_limit(f"ip:{ip}", "GAME_RATE_PER_IP_MIN", 300)  # 來源 IP 維度（含未授權請求）
            auth_blocked(ip, pid)
            is_admin = self._is_admin() and path == "/api/profile"
            if is_admin:
                log.warning("ADMIN delete profile (player id hash=%s)", hash_id(pid))
            with game.store.lock(pid):
                existed = game.store.exists(pid)
                # 授權先於玩家級速率限制：未授權請求不會消耗受害者的額度（Q52）
                try:
                    issued = None if is_admin else game.authorize(pid, token, create=path in CREATE_ROUTES)
                except GameError as e:
                    if e.code == "unauthorized":
                        auth_failed(ip, pid)
                    raise
                if issued and not existed:  # 新建檔：每 IP 每小時上限（Q53）
                    try:
                        rate_limit(f"new:{ip}", "GAME_NEW_PER_IP_HOUR", 200, window=3600.0)
                    except BadRequest:
                        game.store.delete(pid)
                        raise BadRequest("too many new players from this address", "quota_exceeded")
                rate_limit(f"p:{pid}")
                try:
                    out = fn()
                except Exception:
                    if issued:  # 簽發後這次請求失敗：還原，避免玩家被自己的新 token 鎖在外面
                        if existed:
                            prof = game.store.load(pid)
                            prof["token_hash"] = None
                            game.store.save(prof)
                        else:
                            game.store.delete(pid)
                    raise
            if issued and isinstance(out, dict):
                out["token"] = issued
            return out

        def do_POST(self):
            path = urlparse(self.path).path
            if not path.startswith("/api/"):
                return self._json({"error": "not found", "code": "not_found"}, 404)

            def run():
                b = self._body()
                dev = dev_enabled()
                hour = _int(b.get("hour"), "hour", 0, 23)
                if not dev:
                    hour = None  # Q13：時間模擬只在開發模式有效
                sev = _int(b.get("severity"), "severity", 1, 3, default=coach.DEFAULT_SEVERITY, clamp=True)
                reveal = dev and b.get("reveal") is True
                player = lambda: _player(b)  # noqa: E731
                persona = lambda: _persona(game, b)  # noqa: E731
                routes = {
                    "/api/achievements": lambda: achievements.state(game.store, player()),
                    "/api/quiz/state": lambda: quiz.state(game.store, player()),
                    "/api/quiz/start": lambda: quiz.start(game.store, player()),
                    "/api/quiz/answer": lambda: quiz.answer(
                        game.store, player(), b.get("attempt_id"), b.get("question_id"),
                        b.get("choice"), b.get("confidence")),
                    "/api/nickname": lambda: game.set_nickname(player(), _str(b, "nickname", False)) or {"ok": True},
                    "/api/prefs": lambda: {"prefs": game.set_prefs(player(), b.get("prefs"))},
                    "/api/consent": lambda: {"consent": game.set_consent(
                        player(), b.get("version"), b.get("accepted", True))},
                    "/api/profile/delete": lambda: game.delete_profile(player()),
                    "/api/start": lambda: game.start(player(), persona(), _str(b, "gender", False) or None,
                                                     hour, reveal),
                    "/api/message": lambda: game.send(player(), persona(), _str(b, "text", False),
                                                      _str(b, "choice_id", False), sev, hour, reveal),
                    "/api/flag": lambda: game.flag(player(), persona(), _int(b.get("msg_id"), "msg_id", 0, 10**9)
                                                   if b.get("msg_id") is not None else _missing("msg_id")),
                    "/api/review": lambda: game.review(player(), persona(), sev, b.get("finish") is True),
                    "/api/resume": lambda: game.resume(player(), persona(), reveal, b.get("confirm") is True),
                    "/api/reset": lambda: game.reset(player(), persona()) or {"ok": True},
                }
                if path == "/api/admin/migrate":
                    ip = self.client_address[0]
                    rate_limit(f"ip:{ip}", "GAME_RATE_PER_IP_MIN", 300)
                    auth_blocked(ip, "admin")
                    if not self._is_admin():
                        auth_failed(ip, "admin")
                        raise BadRequest("invalid or missing token", "unauthorized")
                    log.warning("ADMIN migrate legacy profile (player id hash=%s)", hash_id(player()))
                    return game.migrate_legacy(player())
                if path not in routes:
                    return None
                token = self.headers.get("X-Player-Token") or b.get("token")
                if token is not None and not isinstance(token, str):
                    raise BadRequest("token must be a string")
                return self._guarded(path, player(), token, routes[path])

            try:
                out = run()
            except (GameError, BadRequest, ValueError) as e:
                return self._json(*error_body(e))
            except Exception:
                log.exception("unhandled error")
                return self._json({"error": "server error", "code": "server_error"}, 500)
            if out is None:
                return self._json({"error": "not found", "code": "not_found"}, 404)
            return self._json(out)

    return Handler


def _missing(name):
    raise BadRequest(f"missing field: {name}")


def main():
    port = int(os.environ.get("PORT", 8000))
    try:
        game = build_game()
    except PersonaLoadError as e:  # Q6：缺 prompt 檔時明確報錯並結束
        print(f"啟動失敗：{e}", file=sys.stderr)
        raise SystemExit(1)
    # 第二道 safety 分類器：Claude 模式下預設啟用（GAME_SAFETY_LLM=0 可關）；mock 模式沒有 LLM，不適用。
    # 啟用時玩家文字會送到外部 LLM，同意文字（static/index.html，CONSENT_VERSION v2）已如實說明。尚未用真 API 實測。
    if game.llm.name != "mock" and os.environ.get("GAME_SAFETY_LLM", "1") != "0":
        from engine.llm import make_safety_classifier
        clf = make_safety_classifier(game.llm)
        print("safety 第二道分類器：" + ("已啟用（玩家文字會送外部 LLM；未實測）" if clf and game.install_safety_classifier(clf) else "無法啟用"))
    else:
        print("safety 第二道分類器：未啟用（mock 模式或 GAME_SAFETY_LLM=0）；目前只有規則式 safety")
    admin = os.environ.get("GAME_ADMIN_TOKEN")
    if admin and len(admin) < 16:
        print("警告：GAME_ADMIN_TOKEN 少於 16 字元，容易被猜中；請改用更長的隨機字串。", file=sys.stderr)
    days = float(os.environ.get("GAME_RETENTION_DAYS", "0") or 0)
    if days > 0:  # 保存期限（Q42）：啟動時清掉超過期限沒更新的存檔
        print(f"已清理 {game.store.purge_older_than(days)} 個過期存檔（保存 {days:g} 天）")
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(game))
    print(f"醒醒吧！戀愛腦 → http://localhost:{port}  （AI 模式：{game.llm.name}）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
