"use strict";

const SEV_NAMES = { 1: "溫柔", 2: "毒舌", 3: "地獄" };
const STATUS_NAMES = { caught: ["check", "抓到"], missed: ["x", "漏掉"], false_positive: ["warn", "誤判（這句其實還好）"] };

/* ---------- 圖示（sprite 在 index.html；24x24、2px 描邊、currentColor；一律 aria-hidden） ---------- */
const SVGNS = "http://www.w3.org/2000/svg";
function ico(name, cls) {
  const sv = document.createElementNS(SVGNS, "svg");
  sv.setAttribute("class", "ic" + (cls ? " " + cls : ""));
  sv.setAttribute("aria-hidden", "true");
  sv.setAttribute("focusable", "false");
  const u = document.createElementNS(SVGNS, "use");
  u.setAttribute("href", "#i-" + name);
  sv.append(u);
  return sv;
}
/* 後端 / 人格資料若混進 emoji，介面標籤類字串一律先過濾（NPC 對話與玩家輸入不套用） */
function stripEmoji(t) {
  return t == null ? "" : String(t).replace(/\p{Extended_Pictographic}|\uFE0F|\u200D/gu, "").replace(/\s{2,}/g, " ").trim();
}
/* 以「圖示 + 文字」重建節點內容 */
function setIconText(node, name, text) { node.replaceChildren(ico(name), document.createTextNode(text)); return node; }
let STAGE_COUNT = 5;   // 之後由 API 的 stage_total 覆蓋
const CONSENT_VERSION = "v2-2026-11";
const MIN_ID_LEN = 16;
const ERR_TEXT = {
  rate_limited: "嘗試太頻繁，請稍後再試。",
  quota_exceeded: "目前無法建立新玩家，請聯絡測試主持人。",
  cooldown: "剛剛才暫停過，先休息一下，約 10 分鐘後再回到遊戲。",
  resume_limit: "這一局已經回到遊戲 3 次了，建議換個對象，或休息一下明天再玩。",
  not_resumable: "這局目前不能回到遊戲。",
  invalid_choice: "這個選項已經過期了，請重新選擇。",
  not_finished: "這局還沒結束，請用「結束並結算」。",
};
const SOS = [  // fallback，正常情況讀 /api/resources
  { number: "1925", name: "安心專線", note: "24 小時，心情低落、想傷害自己時" },
  { number: "165", name: "165 反詐騙諮詢專線", note: "懷疑被騙、正被要求匯款或買點數時" },
  { number: "113", name: "113 保護專線", note: "遭受暴力、跟蹤、性侵或脅迫時" },
];
const SOON = {
  club: ["users", "暈船互助會", "匿名分享、互相提醒的小社群。開發中，敬請期待。"],
};

/* ---------- NPC 頭像（純裝飾 inline SVG；未知人格退回通用人像圖示） ---------- */
const AV_FACE = '<circle cx="32" cy="30" r="12" class="av-skin"/><path d="M19.5 29C19.5 17 26 15 32 15s12.500 2 12.500 14c-3-5-7-7-12.500-7s-9.500 2-12.500 7z" class="av-hair"/>' +
  '<circle cx="27.500" cy="31" r="1.600" class="av-eye"/><circle cx="36.500" cy="31" r="1.600" class="av-eye"/><path d="M29 37h6" class="av-mouth"/>';
const AV_BODY = '<path d="M9.600 52Q32 36 54.400 52A30 30 0 0 1 9.600 52z" class="av-body"/>';
const AVATARS = {
  // 迴避：玻璃門 + 距離線
  avoidant: AV_BODY + AV_FACE + '<rect x="33" y="9" width="19" height="42" rx="2" class="av-glass"/><path d="M38 14l8 0M38 19l5 0" stroke="#fff" stroke-width="1.500" stroke-linecap="round"/>' +
    '<path d="M9 14h17M9 11v6M26 11v6" class="av-line" stroke-dasharray="3 2.500"/>',
  // 依賴：纏繞線 + 愛心
  dependent: AV_BODY + AV_FACE + '<path d="M8 42C18 22 44 60 56 38S30 8 14 22" class="av-line"/><path d="M47 15c-3-4-8 0-4.500 4L47 23l4.500-4c3.500-4-1.500-8-4.500-4z" class="av-pc"/>',
  // 焦慮：已讀泡泡
  anxious: AV_BODY + AV_FACE + '<path d="M37 8h15a6 6 0 0 1 0 12h-9l-5 4 1-4a6 6 0 0 1-2-12z" class="av-white"/><path d="M41 14l2.500 2.500 4-5M46 14l2.500 2.500 4-5" class="av-tick"/>',
  // 騙子：金幣 + 面具
  scammer: AV_BODY + AV_FACE + '<rect x="20" y="27" width="24" height="8" rx="4" class="av-pc"/><circle cx="27.500" cy="31" r="1.800" fill="#fff"/><circle cx="36.500" cy="31" r="1.800" fill="#fff"/>' +
    '<circle cx="50" cy="15" r="7.500" class="av-coin"/><circle cx="50" cy="15" r="4.200" fill="none" stroke="#b8860b" stroke-width="1.200"/><path d="M50 12v6" stroke="#b8860b" stroke-width="1.400" stroke-linecap="round"/>',
  // 渣男／渣女：多框拼貼
  player: '<rect x="11" y="11" width="15" height="15" rx="2" transform="rotate(-8 18 18)" class="av-frame"/><rect x="38" y="10" width="15" height="15" rx="2" transform="rotate(7 45 17)" class="av-frame"/><rect x="24" y="5" width="15" height="12" rx="2" class="av-frame"/>' + AV_BODY + AV_FACE,
};
function avatarSvg(pid) {
  const inner = AVATARS[pid];
  if (!inner) return null;
  const tpl = document.createElement("template");
  tpl.innerHTML = '<svg viewBox="0 0 64 64" aria-hidden="true" focusable="false"><circle cx="32" cy="32" r="30" class="av-bg"/>' + inner + '<circle cx="32" cy="32" r="30" class="av-ring"/></svg>';
  return tpl.content.firstChild;
}
function setAvatar(node, pid) {
  node.replaceChildren();
  const sv = avatarSvg(pid);
  node.classList.toggle("has-svg", !!sv);
  if (sv) { node.dataset.p = pid; node.append(sv); }
  else { delete node.dataset.p; node.append(ico("user")); }
}
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const $ = (id) => document.getElementById(id);
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* 無痕模式 */ } },
};

const S = {
  dev: false,
  resources: null,
  muted: false,
  shownSafety: null,
  player: null,
  personas: [],
  current: null,     // persona id
  state: null,       // 伺服器回傳的局面
  gender: "",
  busy: false,
  token: "",
  muted: false,
  uncomfortable: false,
  consentOk: false,
  stageSeen: {},
};

function newPlayerId() {
  const abc = "abcdefghijklmnopqrstuvwxyz0123456789";
  const buf = new Uint8Array(20);
  crypto.getRandomValues(buf);
  return "p" + Array.from(buf, (b) => abc[b % abc.length]).join("");   // 21 碼
}
function playerId() {
  let id = store.get("lb_player", "");
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{15,63}$/.test(id)) {   // 新版 ID >= 16 碼；較短的舊 ID 視為舊資料
    if (id) S.legacy = true;
    id = newPlayerId();
    store.set("lb_player", id);
    store.set("lb_idv", "2");
  } else if (!store.get("lb_token", "") && store.get("lb_idv", "") !== "2") {
    S.legacy = true;   // 有舊 ID 卻沒有 token：後端已不認舊存檔，不可自動重送
  }
  return id;
}
function legacyPrompt() {
  confirmBox("需要重新開始",
    "偵測到這台裝置上是舊版的玩家資料，沒有憑證，伺服器已不再接受。請用新的身分重新開始（舊資料無法找回）。",
    () => resetIdentity(), "重新開始");
}

class ApiError extends Error {
  constructor(data, status, statusText) {
    super(data.error || statusText || "error");
    this.status = status;
    this.code = data.code || "";
  }
}

async function api(path, body, method) {
  const headers = {};
  if (S.token) headers["X-Player-Token"] = S.token;
  const opt = { headers };
  if (body) { opt.method = method || "POST"; headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  else if (method) opt.method = method;
  const res = await fetch(path, opt);
  let data = {};
  try { data = await res.json(); } catch { /* 非 JSON */ }
  if (!res.ok) throw new ApiError(data, res.status, res.statusText);
  if (typeof data.token === "string" && data.token) { S.token = data.token; store.set("lb_token", data.token); }
  return data;
}

function authLost() {
  confirmBox("憑證遺失或不符",
    "伺服器不認得這台裝置目前的玩家憑證（可能遺失、已過期，或是舊版資料），所以不能讀取或修改這份資料。\n\n你可以用新的身分重新開始（舊資料無法找回，會依保存期限清除）。",
    () => resetIdentity(), "重新開始");
}
function resetIdentity() {
  S.legacy = false;
  ["lb_player", "lb_token", "lb_idv", "lb_nick", "lb_sev", "lb_theme", "lb_consent"].forEach((k) => { try { localStorage.removeItem(k); } catch { /* */ } });
  S.token = ""; S.player = playerId(); S.prefsApplied = false; S.consentOk = false;
  S.muted = false; S.uncomfortable = false; S.current = null; S.state = null;
  $("nickname").value = "";
  $("severity").value = "1"; syncSev(); syncPrefsUi(); applyTheme("");
  updateConsentUi();
  show("home");
}
/* 統一錯誤處理：依 code 判斷，不比對訊息文字。回傳 true 表示已處理 */
function handleErr(e, prefix) {
  // 第 6 輪：授權失敗一律 401 unauthorized（憑證無效、新玩家、舊存檔都一樣）
  if (e.code === "unauthorized" || e.status === 401) { authLost(); return true; }
  const msg = ERR_TEXT[e.code] || (e.status === 429 ? ERR_TEXT.rate_limited : "");
  toast(msg || (prefix ? prefix + e.message : e.message));
  return !!msg;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2200);
}

function show(screen) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.toggle("active", s.id === "screen-" + screen));
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

const persona = (id) => S.personas.find((p) => p.id === id);
const severity = () => Number($("severity").value);
const devOpts = () => (S.dev ? {
  reveal: $("dev-reveal").checked,
  hour: $("dev-hour").value === "" ? null : Number($("dev-hour").value),
} : {});
const isDevReveal = () => S.dev && $("dev-reveal").checked;
const resources = () => (S.resources && S.resources.length ? S.resources : SOS);

async function loadConfig() {
  try {
    const r = await api("/api/resources");
    if (Array.isArray(r.resources) && r.resources.length) S.resources = r.resources;
    S.dev = !!r.dev;
  } catch { S.dev = false; /* 使用內建 fallback */ }
  $("btn-dev").classList.toggle("hidden", !S.dev);
  if (!S.dev) $("dev-panel").classList.add("hidden");
  fillResList($("sos-res"), resources());
}
async function savePrefs(prefs) {
  if (!S.player) return;
  try { await api("/api/prefs", { player: S.player, prefs }); }
  catch (e) { if (!handleErr(e)) toast("設定沒有存成功，下次進來可能會恢復原樣。"); }
}

/* ---------- 對話框（焦點管理）/ 主題 ---------- */
const focusStack = [];
const visibleModals = () => [...document.querySelectorAll(".modal")].filter((x) => !x.classList.contains("hidden"));
function syncInert() {
  const vis = visibleModals();
  const top = vis[vis.length - 1];
  document.querySelectorAll(".screen").forEach((x) => { x.inert = vis.length > 0; });
  document.querySelectorAll(".modal").forEach((x) => { x.inert = !!top && x !== top; });
}
function focusables(root) {
  return [...root.querySelectorAll("button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])")]
    .filter((x) => !x.disabled && !x.closest(".hidden") && x.offsetParent !== null);
}
function openModal(id) {
  focusStack.push(document.activeElement);
  const m = $(id);
  m.classList.remove("hidden");
  syncInert();
  const f = focusables(m)[0];
  if (f) f.focus();
}
function closeModal(id) {
  $(id).classList.add("hidden");
  syncInert();
  const back = focusStack.pop();
  if (back && document.contains(back) && !back.closest("[inert]")) back.focus();
}
document.addEventListener("keydown", (e) => {
  const vis = visibleModals();
  const m = vis[vis.length - 1];
  if (!m) return;
  if (e.key === "Escape") { if (m.id !== "safety-modal") closeModal(m.id); return; }   // 危機提示不能用 Esc 略過
  if (e.key !== "Tab") return;
  const f = focusables(m);
  if (!f.length) { e.preventDefault(); return; }
  const first = f[0], last = f[f.length - 1];
  if (!m.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
});

function confirmBox(title, text, yes, yesLabel) {
  $("confirm-title").textContent = title;
  $("confirm-text").textContent = text;
  $("confirm-yes").textContent = yesLabel || "確定";
  $("confirm-yes").onclick = () => { closeModal("confirm-modal"); yes(); };
  $("confirm-no").onclick = () => closeModal("confirm-modal");
  openModal("confirm-modal");
}

function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
}
function toggleTheme() {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = dark ? "light" : "dark";
  applyTheme(next);
  store.set("lb_theme", next);
  savePrefs({ theme: next });
}

function fillResList(ul, list) {
  ul.replaceChildren();
  for (const r of list) {
    const li = el("li");
    const a = el("a", "", r.number);
    a.href = "tel:" + r.number;
    a.setAttribute("aria-label", `撥打 ${r.number} ${r.name}`);
    li.append(a, el("div", "", r.name), el("div", "fine", r.note));
    ul.append(li);
  }
}

function showSoon(key) {
  const [icon, title, text] = SOON[key];
  const b = $("soon-body");
  b.replaceChildren((() => { const d = el("div", "big-emoji"); d.setAttribute("aria-hidden", "true"); d.append(ico(icon)); return d; })(), el("h3", "", title), el("p", "", text));
  openModal("soon-modal");
}

/* ---------- 偏好 / 同意 ---------- */
function applyProfile(prof) {
  const pr = prof.prefs || {};
  if (!S.prefsApplied) {
    S.prefsApplied = true;
    if ([1, 2, 3].includes(Number(pr.severity))) { $("severity").value = String(pr.severity); }
    if (["light", "dark"].includes(pr.theme)) { applyTheme(pr.theme); store.set("lb_theme", pr.theme); }
    S.muted = pr.mute_coach === true;
    S.uncomfortable = pr.feel_uncomfortable === true;
  }
  S.consentOk = !!(prof.consent && prof.consent.accepted === true && prof.consent.version === CONSENT_VERSION);
  syncSev(); syncPrefsUi(); updateConsentUi();
}
function syncPrefsUi() {
  const m = $("btn-mute"), u = $("btn-uncomfortable"), sev = $("severity");
  m.setAttribute("aria-pressed", String(S.muted));
  setIconText(m, S.muted ? "volume" : "mute", S.muted ? "取消靜音" : "靜音教練");
  u.setAttribute("aria-pressed", String(S.uncomfortable));
  setIconText(u, "uncomfortable", S.uncomfortable ? "解除「我不舒服」" : "我不舒服");
  if (S.uncomfortable) sev.value = "1";
  sev.disabled = S.uncomfortable;
  $("sev-lock").classList.toggle("hidden", !S.uncomfortable);
}
function updateConsentUi() {
  const box = $("consent-box");
  const ok = $("consent-ok");
  box.classList.toggle("hidden", S.consentOk && !S.showConsent);
  $("consent-done").classList.toggle("hidden", !S.consentOk);
  ok.checked = S.consentOk || ok.checked;
  $("btn-enter").disabled = !ok.checked;
}

/* ---------- 選角色 ---------- */
async function loadSelect() {
  const prof = await api("/api/profile?player=" + encodeURIComponent(S.player));
  applyProfile(prof);
  const list = $("persona-list");
  list.replaceChildren();
  for (const p of S.personas) {
    const btn = el("button", "persona");
    btn.dataset.p = p.id;
    if (p.color && !AVATARS[p.id]) btn.style.setProperty("--pc", p.color);   // 已知人格用 CSS token
    const em = el("div", "emoji");
    em.setAttribute("aria-hidden", "true");
    setAvatar(em, p.id);
    btn.append(em);
    const meta = el("div", "meta");
    const nm = p.names ? (S.gender && p.names[S.gender] ? p.names[S.gender] : p.names[p.default_gender]) : "";
    meta.append(el("div", "title", stripEmoji(p.title)), el("div", "tag", stripEmoji(p.tagline)));
    if (p.description && p.description !== p.tagline) meta.append(el("div", "desc", stripEmoji(p.description)));
    if (p.difficulty) {
      const d = el("div", "diff");
      d.setAttribute("role", "img");
      d.setAttribute("aria-label", `難度 ${p.difficulty}／3`);
      for (let i = 1; i <= 3; i++) d.append(ico(i <= p.difficulty ? "star-fill" : "star"));
      meta.append(d);
    }
    if (nm) meta.append(el("div", "names", `${nm}・${p.age} 歲`));
    const sess = prof.sessions[p.id];
    if (sess) {
      meta.append(el("div", "saved", sess.ended
        ? `和 ${sess.npc_name} 的這局已結束（可結算或重開）`
        : `存檔：和 ${sess.npc_name} 聊到第 ${sess.stage} 階段`));
    }
    const go = el("span", "go");
    go.setAttribute("aria-hidden", "true");
    go.append(ico("chev-right"));
    btn.append(meta, go);
    btn.onclick = () => {
      if (reducedMotion()) { openChat(p.id); return; }
      if (btn.classList.contains("picked")) return;
      btn.classList.add("picked");   // 約 .24s 的色環後進入聊天，鍵盤 Enter／Space 同樣走這裡
      setTimeout(() => { btn.classList.remove("picked"); openChat(p.id); }, 240);
    };
    list.append(btn);
  }
  const hist = $("history-list");
  hist.replaceChildren();
  for (const r of [...prof.reviews].reverse()) {
    hist.append(el("li", "", `${r.persona_title}：清醒 ${r.awake_score}／受影響程度 ${r.fooled_index}`));
  }
  $("history-box").classList.toggle("hidden", prof.reviews.length === 0);
}

/* ---------- 聊天 ---------- */
async function openChat(pid) {
  S.current = pid;
  S.state = null;
  S.shownSafety = null;
  S.seenN = null;   // 歷史重繪不播進場動畫
  show("chat");
  const p = persona(pid);
  setAvatar($("npc-avatar"), pid);
  $("npc-name").textContent = stripEmoji(p.title);
  $("npc-stage").textContent = "連線中…";
  $("chat").replaceChildren(typingEl());
  try {
    const st = await api("/api/start", { player: S.player, persona: pid, gender: S.gender || null, ...devOpts() });
    render(st);
  } catch (e) {
    handleErr(e, "開局失敗：");
  }
}

function syncSev() {
  const sev = $("severity");
  $("severity-label").textContent = SEV_NAMES[sev.value];
  sev.setAttribute("aria-valuetext", SEV_NAMES[sev.value]);
  store.set("lb_sev", sev.value);
  $("coach-toggle-label").textContent = "教練尺度：" + SEV_NAMES[sev.value] + (S.uncomfortable ? "（已固定）" : "");
  if (S.uncomfortable) { $("sev-note").classList.add("hidden"); return; }
  const note = $("sev-note");
  const msg = { 2: "毒舌：教練會用吐槽的口氣，針對你的選擇與對方的手法。", 3: "地獄：誇張的戲劇演出，批評的是你的選擇，不是你這個人。" }[sev.value];
  note.textContent = msg || "";
  note.classList.toggle("hidden", !msg);
}

/* 局面階段直接用後端的 state.phase：playing 進行中；final_check 自然結束、尚未結算（可最後補標）；
   locked 已結算（reviewed:true）或被安全機制終止。回傳 playing / final / done 供畫面使用。
   只有舊後端沒回 phase 時才 fallback（ended 且無 safety 視為最後確認，無法分辨已結算，保守地仍開放紅旗鈕，後端會用 locked 擋）。 */
function phaseOf(st) {
  if (!st) return "playing";
  if (st.phase === "playing") return "playing";
  if (st.phase === "final_check") return "final";
  if (st.phase === "locked") return "done";
  if (typeof st.reviewed === "boolean" && st.reviewed) return "done";
  if (!st.ended) return "playing";
  return st.safety ? "done" : "final";
}

function typingEl() {
  const d = el("div", "typing");
  d.append(el("span"), el("span"), el("span"), document.createTextNode(" 對方正在輸入"));
  return d;
}

function render(st) {
  S.state = st;
  if (Number.isInteger(st.stage_total) && st.stage_total > 0) STAGE_COUNT = st.stage_total;
  const p = persona(st.persona_id);
  $("npc-name").textContent = st.npc_name;
  $("npc-name").title = st.npc_name;
  $("npc-stage").textContent = `${stripEmoji(p.title)}｜第 ${st.stage}／${STAGE_COUNT} 階段${st.stage_name ? "：" + stripEmoji(st.stage_name) : ""}`;
  const track = $("stage-track");
  let leveledUp = false;
  track.replaceChildren();
  for (let i = 1; i <= STAGE_COUNT; i++) {
    const up = !reducedMotion() && S.stageSeen[st.persona_id] != null && st.stage > S.stageSeen[st.persona_id] && i === st.stage;
    if (up) leveledUp = true;
    const li = el("li", [i <= st.stage ? "done" : "", i === st.stage ? "cur" : "", i === STAGE_COUNT ? "final" : "", up ? "lvup" : ""].join(" ").trim());
    if (up) setTimeout(() => li.classList.remove("lvup"), 900);
    track.append(li);
  }
  S.stageSeen[st.persona_id] = st.stage;
  if (leveledUp) confetti();
  track.setAttribute("aria-label", `劇情進度：第 ${st.stage} 階段，共 ${STAGE_COUNT} 階段`);
  $("dev-stats").textContent =
    `AI=${st.llm}  stage=${st.stage}  trust=${st.trust}  被騙金額=${st.money_lost.toLocaleString()}  ended=${st.ended}`;

  const chat = $("chat");
  chat.replaceChildren();
  const prevN = (S.seenN != null && S.seenP === st.persona_id) ? S.seenN : st.messages.length;
  st.messages.forEach((m, idx) => {
    const node = renderMsg(m, p);
    if (idx >= prevN && !reducedMotion()) {   // 只有本次新增的訊息才有進場動畫
      node.classList.add("new");
      node.style.setProperty("--d", Math.min(idx - prevN, 3) * 90 + "ms");
    }
    chat.append(node);
  });
  S.seenN = st.messages.length; S.seenP = st.persona_id;
  chat.scrollTop = chat.scrollHeight;

  const choices = $("choices");
  choices.replaceChildren();
  for (const c of st.choices) {
    const b = el("button", "choice", c.text);
    b.onclick = () => send({ choice_id: c.id });
    choices.append(b);
  }
  const ph = phaseOf(st);
  $("btn-review").textContent = ph === "playing" ? "結束並結算" : "看結算";
  $("btn-review").setAttribute("aria-label", ph === "playing" ? "結束這局並結算（結束後不能再標紅旗）"
    : ph === "final" ? "看結算（看了之後不能再標紅旗）" : "看結算");
  const locked = st.ended;
  $("input").disabled = locked;
  $("btn-send").disabled = locked;
  $("input").placeholder = ph === "final" ? "可補標紅旗，再按「看結算」" : locked ? "這局結束了，按右上「看結算」" : "自己打字回覆…";
  if (ph === "final") {
    const fin = el("div", "final-check");
    fin.setAttribute("role", "status");
    fin.append(el("b", "", "最後確認"), document.createTextNode("：還有想補標的可疑訊息嗎？點每則對方訊息旁的旗子按鈕（包含最後一則）。確定了就按右上「看結算」。"));
    chat.append(fin);
    chat.scrollTop = chat.scrollHeight;
  }

  const sf = st.safety;
  if (sf && sf.ends_session !== false) {
    const key = sf.category + "|" + sf.message;
    if (S.shownSafety !== key) { S.shownSafety = key; showSafety(sf); }
  } else if (sf) {
    chat.append(renderNotice(sf));
    chat.scrollTop = chat.scrollHeight;
  }
  if (st.notice && !st.messages.some((x) => x.safety)) chat.append(renderNotice(st.notice));   // 後端若以 notice 回傳不終局提示
}

function stampEl(drop) {
  const tpl = document.createElement("template");
  tpl.innerHTML = '<svg class="stamp' + (drop ? " drop" : "") + '" viewBox="0 0 48 48" role="img" aria-label="已標記" focusable="false"><circle class="st-bg" cx="24" cy="24" r="21"/><circle class="st-in" cx="24" cy="24" r="16.500"/><path class="st-ck" d="M15 25l6 6 12-13"/></svg>';
  return tpl.content.firstChild;
}

/* 升級小慶祝：星星與碎心，約 800ms，只在本次升級播一次（reduced-motion 時 render 不會呼叫） */
function confetti() {
  const host = document.querySelector(".stage-wrap");
  if (!host || reducedMotion()) return;
  const shapes = ['<path class="cf-d" d="M12 2l2.6 6.400 6.900.5-5.300 4.400 1.700 6.700L12 16.200 6.100 20l1.700-6.700L2.500 8.900l6.900-.5z"/>',
    '<path class="cf-a" d="M12 21S3 15.500 3 9.200A4.600 4.600 0 0 1 12 7a4.600 4.600 0 0 1 9 2.200C21 15.500 12 21 12 21z" transform="rotate(8 12 12)"/>',
    '<path class="cf-b" d="M12 3l9 5-4 13H7L3 8z"/>', '<path class="cf-c" d="M12 2l3 7 7 3-7 3-3 7-3-7-7-3 7-3z"/>'];
  const layer = el("div", "confetti");
  layer.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 12; i++) {
    const tpl = document.createElement("template");
    tpl.innerHTML = '<svg viewBox="0 0 24 24" focusable="false">' + shapes[i % shapes.length] + "</svg>";
    const sv = tpl.content.firstChild;
    const ang = (-Math.PI / 2) + (Math.random() - .5) * 2.2;
    const dist = 22 + Math.random() * 28;
    sv.style.setProperty("--x", (14 + Math.random() * 72).toFixed(0) + "%");
    sv.style.setProperty("--dx", (Math.cos(ang) * dist).toFixed(0) + "px");
    sv.style.setProperty("--dy", (Math.sin(ang) * dist - 4).toFixed(0) + "px");
    sv.style.setProperty("--r", ((Math.random() - .5) * 360).toFixed(0) + "deg");
    layer.append(sv);
  }
  host.append(layer);
  setTimeout(() => layer.remove(), 900);
}

function renderNotice(sf) {
  const info = sf.category === "ai_identity" || sf.severity === "info";
  const n = el("div", "notice" + (info ? " info" : " soft"));
  n.setAttribute("role", "status");
  n.append(document.createTextNode(sf.message || ""));
  if (!info) n.append(el("div", "fine", "你剛才那句話觸發了安全提示，原文沒有被保存。"));
  if (!info && sf.resources && sf.resources.length) {
    const box = el("div");
    for (const r of sf.resources) {
      const a = el("a", "", `${r.number} ${r.name}`);
      a.href = "tel:" + r.number;
      box.append(a);
    }
    n.append(box);
  }
  return n;
}

function renderMsg(m, p) {
  if (m.role === "coach") {
    // praise 與 neutral 版型、圖示、標題完全相同，只有文字不同：不能用視覺差異洩漏「這句有沒有紅旗」
    const calm = m.tone === "praise" || m.tone === "neutral";
    const c = el("div", "coach" + (calm ? " calm" : ""));
    c.setAttribute("role", "note");
    const ch = el("b");   // 兩種都是 <b>圖示 + 標題</b> + 內文，DOM 結構一致
    if (calm) setIconText(ch, "note", "教練備註");
    else setIconText(ch, "flame", `教練（${SEV_NAMES[m.severity] || SEV_NAMES[severity()]}）`);
    c.append(ch);
    c.append(document.createTextNode(m.text));
    return c;
  }
  if (m.role === "system" && m.safety) return renderNotice(m.safety);
  if (m.role === "system") return el("div", "sysmsg", m.text);
  if (m.role === "player") {
    const row = el("div", "row me" + (m.meta ? " meta" : ""));
    const b = el("div", "bubble", m.text);   // meta（問 AI 身分）沒有 kind，這裡不依賴 kind
    if (m.meta) b.append(el("div", "meta-tag", "問身分・不計分"));
    row.append(b);
    return row;
  }
  const row = el("div", "row npc" + (m.flagged ? " flagged" : "") + (m.id === S.justFlagged && m.flagged && m.red_flags && m.red_flags.length ? " hit" : ""));
  const av = el("div", "avatar");
  setAvatar(av, p.id);
  av.setAttribute("aria-hidden", "true");
  row.append(av);
  const wrap = el("div", "npc-wrap");
  wrap.append(el("div", "bubble", m.text));
  if (m.flagged) wrap.append(stampEl(m.id === S.justFlagged));   // 檢舉回應之後才有章；命中或誤判外觀相同
  const ph = phaseOf(S.state);
  if (m.red_flags && (m.flagged || ph === "done" || isDevReveal())) {
    const tags = el("div", "flag-tags");
    if (m.red_flags.length === 0 && m.flagged) tags.append(el("span", "ftag miss", "這句其實沒問題"));
    for (const f of m.red_flags) {
      const cls = m.flagged ? "hit" : (ph === "done" ? "miss" : "ghost");
      tags.append(setIconText(el("span", "ftag " + cls), "flag", stripEmoji(f.meaning)));
    }
    if (tags.childElementCount) wrap.append(tags);
  }
  row.append(wrap);
  if (ph !== "done" || m.flagged) {
    const fb = el("button", "flag-btn" + (m.flagged ? " used" : ""));
    fb.append(ico("flag"));
    fb.title = "這句是紅旗！";
    fb.setAttribute("aria-label", m.flagged ? "已檢舉為紅旗" : "檢舉這句為紅旗");
    fb.setAttribute("aria-pressed", String(!!m.flagged));
    fb.disabled = m.flagged || ph === "done";
    fb.onclick = () => flag(m.id);
    row.append(fb);
  }
  return row;
}

async function send(payload) {
  if (S.busy || !S.state || S.state.ended) return;
  S.busy = true;
  $("btn-send").disabled = true;
  $("choices").replaceChildren();
  $("chat").append(typingEl());
  $("chat").scrollTop = $("chat").scrollHeight;
  try {
    const st = await api("/api/message", {
      player: S.player, persona: S.current, severity: severity(), ...devOpts(), ...payload,
    });
    render(st);
  } catch (e) {
    if (e.code === "ended" || e.code === "invalid_choice") {
      try { render(await api("/api/start", { player: S.player, persona: S.current })); } catch (e2) { handleErr(e2); }
    } else render(S.state);
    handleErr(e, "送出失敗：");
  } finally {
    S.busy = false;
    if (!S.state.ended) $("btn-send").disabled = false;
  }
}

async function flag(msgId) {
  try {
    const r = await api("/api/flag", { player: S.player, persona: S.current, msg_id: msgId });
    toast(r.correct ? "抓到了！" + r.red_flags.map((f) => f.meaning).join("、") : "這句其實還好，別草木皆兵～");
    const m = S.state.messages.find((x) => x.id === msgId);
    m.flagged = true;
    m.red_flags = r.red_flags;
    S.justFlagged = msgId;
    render(S.state);
    S.justFlagged = null;
  } catch (e) {
    if (e.code === "ended" || e.code === "locked") {
      toast("這局已結算或結束，不能再補標紅旗了");
      try { render(await api("/api/start", { player: S.player, persona: S.current })); } catch { /* 忽略 */ }
    } else handleErr(e, "檢舉失敗：");
  }
}

/* ---------- 結算 ---------- */
function svg(tag, attrs, text) {
  const n = document.createElementNS(SVGNS, tag);
  for (const k in attrs || {}) n.setAttribute(k, attrs[k]);
  if (text != null) n.textContent = text;
  return n;
}

function ring(score) {
  const R = 70, C = 2 * Math.PI * R;
  const g = svg("svg", { class: "ring", viewBox: "0 0 170 170", role: "img", "aria-label": `清醒分數 ${score} 分（滿分 100）` });
  g.append(svg("circle", { class: "track", cx: 85, cy: 85, r: R }));
  const v = svg("circle", { class: "val", cx: 85, cy: 85, r: R, "stroke-dasharray": C, "stroke-dashoffset": C * (1 - score / 100) });
  const animate = !reducedMotion() && score > 0;
  const nTxt = svg("text", { class: "n", x: 85, y: 94 }, String(animate ? 0 : score));
  if (animate) {
    const t0 = performance.now();
    const tick = (now) => {
      const k = Math.min(1, (now - t0) / 900);
      nTxt.textContent = String(k >= 1 ? score : Math.round(score * (1 - Math.pow(1 - k, 3))));
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
  g.append(v, nTxt, svg("text", { class: "s", x: 85, y: 116 }, "清醒分數 / 100"));
  return g;
}

function meter(title, valueText, sub, icon) {
  const m = el("div", "meter");
  const h = el("div", "meter-head");
  const t = el("span", "");
  if (icon) t.append(ico(icon));
  t.append(document.createTextNode(title));
  h.append(t, el("small", "", valueText));
  m.append(h);
  if (sub) m.append(el("div", "fine", sub));
  return m;
}

function pctBar(pct) {
  const t = el("div", "bar-track");
  const f = el("div", "bar-fill");
  f.style.transform = "scaleX(0)";
  t.append(f);
  requestAnimationFrame(() => requestAnimationFrame(() => (f.style.transform = "scaleX(" + pct / 100 + ")")));
  return t;
}

function reviewClick() {
  const ph = phaseOf(S.state);
  if (ph === "playing") {
    confirmBox("結束這局並結算？", "結算後這局就結束了，不能再回來標紅旗，也不能繼續聊。確定要現在看結果嗎？", () => review(true));
  } else if (ph === "final") {
    confirmBox("看結算？", "看了結算就不能再補標紅旗了。還有想補標的對方訊息嗎？", () => review(false), "看結算");
  } else review(false);
}

async function review(finish) {
  try {
    const r = await api("/api/review", { player: S.player, persona: S.current, severity: severity(), ...(finish ? { finish: true } : {}) });
    const s = r.scores;
    const newAchievements = (r.achievements && r.achievements.newly_unlocked) || [];
    const body = $("review-body");
    body.replaceChildren();

    const hero = el("div", "score-hero");
    hero.append(ring(s.awake_score), el("div", "grade", stripEmoji(s.grade)));
    if (s.grade_note) hero.append(el("p", "grade-note", s.grade_note));
    body.append(hero);

    // 紅旗辨識率
    const rec = meter("紅旗辨識率", s.recall == null ? "這局沒有紅旗" : `${s.recall}%（${s.flags_caught}/${s.flags_total}）`, null, "flag");
    if (s.recall != null) rec.append(pctBar(s.recall));
    if (s.false_positives) rec.append(el("div", "fine", `另外誤判 ${s.false_positives} 句（草木皆兵）`));
    body.append(rec);

    // 受影響程度（綠到紅漸層，指針標位置）
    const fo = meter("受影響程度", `${s.fooled_index} / 100`, "越低越好", "heart-broken");
    const ft = el("div", "bar-track fooled-track");
    const mask = el("div", "mask"); mask.style.width = (100 - s.fooled_index) + "%";
    const pin = el("div", "pin"); pin.style.left = s.fooled_index + "%";
    ft.append(mask, pin);
    fo.append(ft);
    body.append(fo);

    // 清醒 vs 戀愛腦
    const total = s.awake_choices + s.brain_choices;
    const sp = meter("回覆傾向", total ? `${s.awake_choices} 清醒 : ${s.brain_choices} 戀愛腦` : "沒有選項回覆", null, "brain");
    if (total) {
      const bar = el("div", "split");
      const a = el("i", "a"), b = el("i", "b");
      a.style.width = (s.awake_choices / total * 100) + "%"; b.style.width = (s.brain_choices / total * 100) + "%";
      bar.append(a, b);
      sp.append(bar);
      const lg = el("div", "legend");
      const k1 = el("span", "", "清醒"), k2 = el("span", "", "戀愛腦");
      k1.prepend(el("i", "sw a")); k2.append(el("i", "sw b"));
      lg.append(k1, k2);
      sp.append(lg);
    }
    body.append(sp);
    if (s.money_lost) body.append(el("p", "fine", `被騙金額（遊戲幣）：${s.money_lost.toLocaleString()} 元`));

    const cb = el("div", "coach-box");
    cb.append(el("b", "", `教練總評（${stripEmoji(r.coach.severity_name)}）`), document.createTextNode(r.coach.comment));
    body.append(cb);

    if (r.coach.items.length) {
      body.append(el("h3", "", "逐句覆盤"));
      const ul = el("ul", "items");
      for (const it of r.coach.items) {
        const li = el("li", it.status);
        const stage = it.stage ? `第 ${it.stage} 階段` : "";
        li.append(setIconText(el("div", "st " + it.status), STATUS_NAMES[it.status][0], STATUS_NAMES[it.status][1]),
          el("div", "item-meta", [stage, it.msg_id != null ? `訊息 #${it.msg_id}` : ""].filter(Boolean).join("・")),
          el("div", "bubble", it.text));
        if (it.player_reply) li.append(el("div", "reply", "你：" + it.player_reply));
        if (it.flags.length) {
          const fl = el("div", "fine flag-line");
          it.flags.forEach((f) => fl.append(setIconText(el("span", "ftag-inline"), "flag", stripEmoji(f.meaning))));
          li.append(fl);
        }
        ul.append(li);
      }
      body.append(ul);
    }
    openModal("review-modal");
    if (newAchievements.length) {
      const names = (r.achievements.badges || []).filter(b => newAchievements.includes(b.id)).map(b => b.title);
      toast("新成就解鎖：" + names.join("、"));
    }
    try { render(await api("/api/start", { player: S.player, persona: S.current })); }   // 取得完整標示的 state
    catch (e2) { if (!handleErr(e2)) { S.state.ended = true; render(S.state); } }
  } catch (e) {
    if (e.code === "not_finished") { reviewClick(); return; }
    handleErr(e, "結算失敗：");
  }
}

function showSafety(sf) {
  const info = sf.category === "ai_identity" || sf.severity === "info";
  const pause = sf.category === "pause";
  S.safetyCat = sf.category;
  $("safety-modal").querySelector(".sheet").classList.toggle("info", info);
  $("safety-title").textContent = info ? "關於「對方」" : pause ? "已暫停" : "先停一下";
  $("safety-msg").textContent = sf.message;
  const res = sf.resources || [];
  fillResList($("safety-res"), res);
  $("safety-res").classList.toggle("hidden", res.length === 0);
  $("safety-disc").textContent = sf.disclaimer || "";
  $("safety-priv").classList.toggle("hidden", info);
  const canResume = !!(S.state && S.state.can_resume) && !S.resumeBlocked;
  $("safety-resume").classList.toggle("hidden", !canResume);
  $("safety-again").classList.toggle("hidden", canResume);   // category 'model' 等未知類別也走這個通用出口
  openModal("safety-modal");
}

async function resetCurrent() {
  try {
    await api("/api/reset", { player: S.player, persona: S.current });
    S.resumeBlocked = false;
    closeModal("review-modal");
    openChat(S.current);
  } catch (e) { handleErr(e, "重開失敗："); }
}

async function doResume(confirm) {
  try {
    S.shownSafety = null;
    const st = await api("/api/resume", { player: S.player, persona: S.current, ...(confirm ? { confirm: true } : {}), ...devOpts() });
    closeModal("safety-modal");
    render(st);
  } catch (e) {
    if (e.code === "resume_limit" || e.code === "cooldown") S.resumeBlocked = true;
    handleErr(e, "無法回到遊戲：");
    if (S.resumeBlocked) { $("safety-resume").classList.add("hidden"); $("safety-again").classList.remove("hidden"); }
  }
}
function resumeClick() {
  if (S.safetyCat === "too_painful") {
    fillResList($("resume-res"), resources());
    closeModal("safety-modal");
    openModal("resume-modal");
  } else doResume(false);
}

/* ---------- 綁定 ---------- */
async function restoreProfile() {
  // 第 6 輪：沒有 token 就不呼叫 GET /api/profile（新玩家和無效憑證都回 401），直接當新玩家
  if (S.legacy) { legacyPrompt(); return; }
  if (!S.token) return;
  try { applyProfile(await api("/api/profile?player=" + encodeURIComponent(S.player))); }
  catch (e) { if (e.status === 401) authLost(); }
}

function init() {
  const arc = $("hero-arc");
  if (arc) for (const pid of ["avoidant", "dependent", "player", "anxious", "scammer"]) {
    const d = el("div", "avatar"); setAvatar(d, pid); arc.append(d);
  }
  if (arc && !reducedMotion()) {   // 首頁唯一的編排時刻：貼紙依序彈出，播一次，結束後移除 class 避免重播
    const stickers = [...arc.children];
    stickers.forEach((d, i) => { d.style.setProperty("--i", i); d.classList.add("pop"); });
    const done = () => stickers.forEach((d) => d.classList.remove("pop"));
    stickers[stickers.length - 1].addEventListener("animationend", done, { once: true });
    setTimeout(done, 1100);
  }
  S.player = playerId();
  S.token = store.get("lb_token", "");
  $("nickname").value = store.get("lb_nick", "");

  const consent = $("consent-ok");
  consent.onchange = () => { $("btn-enter").disabled = !consent.checked; };
  $("btn-consent-show").onclick = () => { S.showConsent = !S.showConsent; updateConsentUi(); };
  $("btn-delete").onclick = () => confirmBox("刪除我的資料？",
    "按下確定，會刪除這個玩家在伺服器上的存檔（暱稱、所有對話紀錄、分數、小測驗與成就紀錄）、同意紀錄，以及損毀存檔的隔離備份。刪除後無法復原，這台裝置會換成全新的玩家身分。",
    async () => {
      try {
        await api("/api/profile?player=" + encodeURIComponent(S.player), null, "DELETE");
        resetIdentity();
        toast("已刪除你的資料");
      } catch (e) { handleErr(e, "刪除失敗："); }
    }, "刪除");
  $("btn-enter").onclick = async () => {
    if (S.legacy) { legacyPrompt(); return; }
    const nick = $("nickname").value.trim();
    store.set("lb_nick", nick);
    try {
      S.personas = await api("/api/personas");
      if (S.personas[0] && S.personas[0].stage_total) STAGE_COUNT = S.personas[0].stage_total;
      if (!S.consentOk) {   // 首次（或版本更新）：記錄同意，同時也會簽發 token
        await api("/api/consent", { player: S.player, version: CONSENT_VERSION, accepted: true });
      }
      await api("/api/nickname", { player: S.player, nickname: nick });
      await loadSelect();
      S.consentOk = true; S.showConsent = false;
      show("select");
    } catch (e) {
      if (!handleErr(e)) toast("連不到伺服器：" + e.message);
    }
  };
  document.querySelectorAll("[data-go=home]").forEach((b) => (b.onclick = () => show("home")));
  $("btn-back").onclick = () => { loadSelect(); show("select"); };

  $("gender-seg").querySelectorAll("button").forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.g === S.gender));
    b.onclick = () => {
      S.gender = b.dataset.g;
      $("gender-seg").querySelectorAll("button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
      toast("性別只套用在新開的局");
      loadSelect();
    };
  });

  $("form").onsubmit = (e) => {
    e.preventDefault();
    const text = $("input").value.trim();
    if (!text) return;
    $("input").value = "";
    send({ text });
  };

  const sev = $("severity");
  sev.value = store.get("lb_sev", "1");     // 預設溫柔
  syncSev();
  let prevSev = sev.value;
  sev.oninput = () => {
    if (sev.value === "3") {   // 地獄：二次確認
      sev.value = prevSev;
      syncSev();
      openModal("hell-modal");
      return;
    }
    prevSev = sev.value;
    syncSev();
    savePrefs({ severity: Number(sev.value) });
  };
  $("hell-back").onclick = () => closeModal("hell-modal");
  $("hell-ok").onclick = () => { closeModal("hell-modal"); sev.value = "3"; prevSev = "3"; syncSev(); savePrefs({ severity: 3 }); };
  $("btn-mute").onclick = () => {
    S.muted = !S.muted;
    syncPrefsUi();
    savePrefs({ mute_coach: S.muted });
    toast(S.muted ? "教練已靜音（之後不會再有教練插話，計分照常）" : "教練已取消靜音（靜音期間的回合不會補上）");
  };
  $("btn-uncomfortable").onclick = () => {
    S.uncomfortable = !S.uncomfortable;
    if (S.uncomfortable) { sev.value = "1"; prevSev = "1"; }
    syncSev(); syncPrefsUi();
    savePrefs(S.uncomfortable ? { severity: 1, feel_uncomfortable: true } : { feel_uncomfortable: false });
    toast(S.uncomfortable ? "教練已固定為溫柔。需要的話，點「求助鈕」看求助資源。" : "已解除，可以再調整尺度。");
  };

  S.token = store.get("lb_token", "");
  applyTheme(store.get("lb_theme", ""));
  $("btn-theme").onclick = toggleTheme;
  document.querySelectorAll("[data-theme-toggle]").forEach((b) => (b.onclick = toggleTheme));
  fillResList($("sos-res"), resources());
  const setPanel = (open) => {
    $("coach-panel").classList.toggle("hidden", !open);
    $("coach-toggle").setAttribute("aria-expanded", String(open));
    $("coach-toggle-arrow").replaceChildren(ico(open ? "chev-up" : "chev-down"));
  };
  setPanel(window.innerHeight >= 700);   // 矮螢幕預設收合，把空間留給對話
  $("coach-toggle").onclick = () => setPanel($("coach-panel").classList.contains("hidden"));
  document.querySelectorAll(".sheet").forEach((sh) => {   // 對話框開著時背景 inert，求助鈕要在對話框裡也點得到
    if (sh.closest("#sos-modal, #safety-modal, #resume-modal")) return;
    const b = setIconText(el("button", "linkbtn sos-inline"), "sos", "需要幫助？");
    b.dataset.sos = "";
    sh.append(b);
  });
  document.querySelectorAll("[data-sos]").forEach((b) => (b.onclick = () => openModal("sos-modal")));
  loadConfig();
  restoreProfile();
  document.querySelectorAll("[data-sos]").forEach((b) => (b.onclick = () => openModal("sos-modal")));
  document.querySelectorAll("[data-soon]").forEach((b) => (b.onclick = () => showSoon(b.dataset.soon)));

  $("btn-dev").onclick = () => { const h = $("dev-panel").classList.toggle("hidden"); $("btn-dev").setAttribute("aria-expanded", String(!h)); };
  $("dev-reveal").onchange = () => S.state && render(S.state);
  $("dev-reset").onclick = resetCurrent;
  $("dev-prompt").onclick = async () => {
    try {
      const r = await api(`/api/prompt?player=${encodeURIComponent(S.player)}&persona=${encodeURIComponent(S.current)}`);
      $("prompt-text").textContent = r.prompt;
      openModal("prompt-modal");
    } catch (e) { handleErr(e); }
  };

  $("btn-review").onclick = reviewClick;
  $("review-again").onclick = resetCurrent;
  $("review-other").onclick = () => { closeModal("review-modal"); loadSelect(); show("select"); };
  $("safety-resume").onclick = resumeClick;
  $("resume-wait").onclick = () => { closeModal("resume-modal"); openModal("safety-modal"); };
  $("resume-go").onclick = () => { closeModal("resume-modal"); openModal("safety-modal"); doResume(true); };
  $("safety-again").onclick = () => { closeModal("safety-modal"); resetCurrent(); };
  $("safety-ok").onclick = () => { closeModal("safety-modal"); loadSelect(); show("select"); };
  document.querySelectorAll("[data-close]").forEach((b) => (b.onclick = () => closeModal(b.closest(".modal").id)));
}

init();
