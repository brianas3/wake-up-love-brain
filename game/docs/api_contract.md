# API 契約（後端 B，第 6 輪更新）

通則
- 全部 JSON（UTF-8）。POST 必須 `Content-Type: application/json`，body 必須是 JSON 物件，上限 32 KB；否則 400。
- 錯誤格式：`{"error": "<訊息>", "code": "<代碼>"}`（error 文字給人看，前端請用 code 判斷；code 清單見文末）。400 = 請求有問題（欄位缺失／型別錯／規則不允許）；404 = 路徑不存在（含正式模式的 /api/prompt）；500 = `{"error":"server error"}`，細節只在伺服器 log。
- `player`：`[A-Za-z0-9][A-Za-z0-9_-]{0,63}`，排除 con/nul 等保留名；前端請產生 6–64 碼。
- `severity`（教練尺度）：1 溫柔（預設）、2 毒舌、3 地獄；缺省或非法整數 → 夾到 1–3 / 預設 1；非數字 → 400。
- `hour`：0–23 整數（或省略）；非數字／超範圍 → 400。
- 環境變數 `GAME_DEV=1` 才有：`reveal:true` 生效、`hour` 生效、`GET /api/prompt`。正式模式 reveal/hour 被忽略、/api/prompt 回 404。

## State 物件（start / message / resume / flag 以外多數回應）
```
persona_id, npc_name, gender, stage, stage_total(=5), stage_name,
trust, ended, money_lost, llm,
reviewed            // bool：review 成功後為 true（存進存檔；舊存檔缺欄位視為 false）
phase               // "playing"（進行中）| "final_check"（自然結束、未結算，可最後補標）| "locked"（已結算，或被 safety 終止；不可標旗）
can_resume          // true：safety.category 為 pause / too_painful，可呼叫 /api/resume
flags_reported      // 已檢舉數
flags_caught_so_far // 檢舉中正確的數量（flag 回應本來就會告知對錯，不算洩題）
safety              // null 或 Safety 物件（局被安全機制終止時）
choices: [{id, text}]   // 局結束時為 []。id = "s{stage}_{index}"，只接受當前階段；選項含 neutral、順序每局固定、不要假設數量
messages: [Message]
```
Message（依 role）
- `npc`：`id, role, text, flagged`；已檢舉／局結束／GAME_DEV+reveal 時多 `red_flags:[{code,meaning}]`
- `player`：`id, role, text, kind(brain|awake|neutral)`；問 AI 身分的提問（不計分）會是 `role:"player", meta:true`
- `coach`：`id, role, text, tone(praise|roast|neutral), severity(1-3)`（該則訊息產生時的尺度，不要用目前滑桿）
- `system`：`id, role, text`；若帶 `safety`（Safety 物件）代表這是安全／AI 身分提示，前端可用專屬樣式顯示

Safety 物件
```
category      self_harm | real_violence | real_scam | minor | too_painful | pause | ai_identity | model
severity      high | medium | low | info
ends_session  true（high / medium：局結束）或 false（low 降級提醒、info）
message, model_text, resources:[{name,number,note}]（ai_identity 為 []）, disclaimer
```

## Endpoints
| Method / Path | Request | Response |
|---|---|---|
| GET /api/personas | – | `[{id,title,tagline,emoji,names,age,default_gender,stage_names,stage_total,color,description,difficulty}]` |
| GET /api/resources | – | `{resources:[{name,number,note}], dev:bool}`；`dev` = 伺服器是否以 GAME_DEV=1 啟動，前端用它決定是否顯示開發面板（不要再探測 /api/prompt） |
| GET /api/profile?player= | – | `{player_id,nickname,sessions:{pid:{stage,ended,turns,npc_name}},reviews:[…10],prefs,consent}`；無檔案回空（`prefs:{}`、`consent:null`） |
| DELETE /api/profile?player=　或　POST /api/profile/delete {player} | – | `{ok:true, deleted:bool}`；刪除全部資料（含損毀隔離檔） |
| POST /api/nickname | `{player, nickname?}` | `{ok:true}`；暱稱截 20 字 |
| POST /api/consent | `{player, version:"<1-32 字，英數 . _ ->", accepted?:bool(預設 true)}` | `{consent:{version,accepted,ts}}`；覆寫舊紀錄；版本格式錯／accepted 非布林 → 400。**只記錄、不強制**：未同意時 start / message 照常運作（同意閘門由前端負責）。刪除我的資料時一併刪除 |
| POST /api/prefs | `{player, prefs:{severity?:1-3, theme?:light\|dark\|auto, mute_coach?:bool, feel_uncomfortable?:bool}}` | `{prefs}`（合併後全部）；其他 key／值／型別（含用 1/0 代替 bool）→ 400。`mute_coach=true`：後端不產生教練訊息，但仍照常計分；`feel_uncomfortable=true`：教練尺度一律視為 1（溫柔），忽略請求的 severity |
| POST /api/start | `{player, persona, gender?:"男"\|"女", hour?*, reveal?*}` | State。已有存檔則接續 |
| POST /api/message | `{player, persona, text? \| choice_id?, severity?, hour?*, reveal?*}` | State，可能多 `notice`（見下）。局已結束 → 400 |
| POST /api/flag | `{player, persona, msg_id:int}` | `{msg_id, correct, red_flags:[{code,meaning}], flags_caught_so_far, flags_reported}`；局結束／已結算 → 400 |
| POST /api/review | `{player, persona, severity?, finish?:bool}` | `{scores:{…detect_score,behavior_score,awake_score,grade,…}, coach:{severity,severity_name,comment,items:[{text,status,flags,msg_id,stage,player_reply}]}}`。**局中必須 finish:true**（會結束這局），否則 400；已結束的局不需要 |
| POST /api/resume | `{player, persona}` | State（ended=false）。只有 pause / too_painful 之後可用，否則 400 |
| POST /api/reset | `{player, persona}` | `{ok:true}`；刪該人格的局 |
| GET /api/prompt?player=&persona= | – | `{prompt}`；**僅 GAME_DEV=1**，否則 404 |

(* = 僅 GAME_DEV=1 生效，否則忽略)

## /api/message 的安全分流
`text` 先經 `safety.assess`：
1. **ends_session=true**（self_harm / real_violence / real_scam 第一人稱；minor；pause；too_painful）：局結束，回 State，`ended:true`、`safety` 為 Safety 物件，NPC 不再回話。原文不入庫（pause 的原文照存）。`can_resume` 為 true 時顯示「回到遊戲」按鈕 → POST /api/resume；其他類別只能重開（/api/reset）或離開。
2. **severity=low**（第三人稱、小說、誇飾）：不終局，照常進行本回合，回應多 `notice`（Safety 物件）並在 messages 內多一則帶 `safety` 的 system 訊息。前端顯示提醒＋資源即可。
3. **ai_identity**（真誠詢問是不是 AI／真人）：不終局、不計分（不增加回合數、信任、brain/awake）、不呼叫 LLM。回應多 `notice`（category=ai_identity，resources 為 []），messages 多一則玩家提問（`meta:true`）與一則帶 `safety` 的 system 回答。
4. 模型回 `break_character`：若玩家原文屬 ai_identity → 同 3；否則終局，`safety.category="model"`（severity medium，不可 resume）。

選項 `choice_id` 的 kind 優先；自由輸入由 `scoring.resolve_kind` 判定，戀愛腦的自由輸入會用 `scoring.money_in_text` 抽金額並計入 `money_lost`。

## 錯誤碼速查
| 狀況 | 碼 |
|---|---|
| 非 JSON content-type／壞 JSON／非物件／過大／缺欄位／型別錯／hour、severity、msg_id 非法／player 不合白名單／persona 不存在 | 400 |
| 局未開始、局已結束再 message、局結束後 flag、局中 review 未帶 finish、choice_id 不屬於當前階段、resume 不可用 | 400 |
| 未知路徑、正式模式的 /api/prompt | 404 |
| 未預期例外（LLM 連線失敗已由重試＋fallback 吸收，不會到這裡） | 500 |

## 存檔
`saves/<player>.json`；損毀會改名 `.corrupt-時間戳` 並自動開新局（API 不會 500）。


## 第 5 輪新增：玩家憑證（token）
- 玩家第一次「建立」資料時（`/api/start`、`/api/nickname`、`/api/consent`、`/api/prefs` 之中任何一個先到者），伺服器簽發隨機 token，**只在該次回應 JSON 的頂層 `token` 欄位出現一次**；伺服器只存 SHA-256 雜湊。前端要存起來（localStorage）。
- 之後所有寫入（所有 POST、DELETE /api/profile）與 `GET /api/profile` 都必須帶 token：HTTP header `X-Player-Token: <token>`（建議），POST 也可放 body 欄位 `token`。DELETE 與 GET 只收 header（避免 token 進 URL log）。
- 缺 token、token 不符、玩家不存在一律 → 401 `unauthorized`（第 6 輪起不再區分 403，見後文）。
- 只有「建立型」路由會建檔；`/api/message`、`/api/flag`、`/api/review`、`/api/resume`、`/api/reset` 對不存在的玩家回 400 `not_started`，不會建檔也不會簽發。請求失敗時，剛簽發的 token 會被撤銷，不會留下孤兒檔。
- 舊存檔（機制上線前沒有 token_hash）：第一次建立型請求會「認領」並簽發 token；認領前任何知道 ID 的人都可以讀寫（遷移期限制）。
- **token 遺失**：無法找回。處理：換一個新的玩家 ID 重新開始；舊資料由保存期限清理（`GAME_RETENTION_DAYS`）或管理者以 `X-Admin-Token`（需伺服器設 `GAME_ADMIN_TOKEN`）呼叫 `DELETE /api/profile` 刪除。刪除成功後同 ID 視同新玩家，會再簽發新 token。
- 玩家 ID 最短 8 字元（`GAME_MIN_ID_LEN`，預設 8），字元集不變。前端請改用 `crypto.getRandomValues` 產生 ≥16 碼 ID。
- 匿名建檔總量上限 `GAME_MAX_PLAYERS`（預設 2000），超過 → 429 `quota_exceeded`。每位玩家寫入速率 `GAME_RATE_PER_MIN`（預設 60/分），超過 → 429 `rate_limited`。
- 關閉機制（僅供測試／內部）：`GAME_REQUIRE_TOKEN=0`。

## 第 5 輪新增：行為變更
- **模型拒答（Q31）**：模型回 `break_character` 但玩家原文沒有 safety 觸發 → 不終局、不顯示熱線，用不帶紅旗的 fallback 台詞續局（該 NPC 訊息內部標 `fallback`）。`safety.category="model"` 不再出現。終局只由玩家原文的 safety 決定。
- **resume 把關（Q35）**：`POST /api/resume` 新增 `confirm:bool`。`too_painful` 必須 `confirm:true`（前端先顯示資源與「我現在可以繼續嗎」確認），否則 `confirm_required`；10 分鐘內（`GAME_RESUME_COOLDOWN` 秒）第二次 too_painful → `cooldown`；每局最多 resume 3 次 → `resume_limit`。
- **選項數**：shuffle 人格每階段是 brain + awake 加上從 `neutral_pool` 以每局種子抽的 1~2 個 neutral，總數 3~4，同一局同一階段固定。前端不要假設數量。
- **NPC 正常台詞（Q28）**：mock 約 1/3 回合使用無紅旗的 `mock_clean_lines`（每局種子可重現）。
- **隱私（Q42）**：觸發任何 safety 規則（含 low、pause）的玩家原文不入庫，訊息顯示為「（此訊息觸發安全提示，原文未保存）」，另記 `safety_events`（時間、類別）。
- **ai_identity 上限（Q43）**：每局只記錄前 5 次問答，之後仍回 `notice` 但不再新增訊息。
- **輸出攔截（Q45）**：NPC 回覆含網址、10 位以上連續數字、錢包地址或紅旗代碼 → 視為壞輸出，重試／fallback。

## 錯誤 code 清單
| code | HTTP | 意義 |
|---|---|---|
| bad_request | 400 | 欄位缺失／型別錯／範圍錯／ID 太短／persona 不存在／其他請求問題 |
| invalid_choice | 400 | choice_id 不屬於當前階段或索引無效 |
| not_started | 400 | 該人格還沒有開局 |
| ended | 400 | 局已結束，不能再回覆 |
| locked | 400 | 局已結束／已結算，不能再檢舉紅旗 |
| not_finished | 400 | 局中呼叫 review 沒帶 finish:true |
| not_resumable | 400 | 目前狀態不能 resume |
| confirm_required | 400 | too_painful 的 resume 需要 confirm:true |
| cooldown | 400 | 短時間內重複 too_painful，暫不可 resume |
| resume_limit | 400 | 這局 resume 次數用完 |
| unauthorized | 401 | 缺 token／token 錯／玩家不存在／無 token 的舊存檔（同一種回應） |
| forbidden | 403 | （已不使用：保留代碼，第 6 輪起 token 錯誤一律 401 `unauthorized`） |
| not_found | 404 | 路徑不存在（含正式模式的 /api/prompt） |
| quota_exceeded | 429 | 玩家總量上限 |
| rate_limited | 429 | 寫入太頻繁 |
| server_error | 500 | 未預期錯誤（細節只在伺服器 log） |

## 前端需配合的變更
1. 存取並送出 token：從 `/api/start` 等回應的 `token` 欄位取得並存 localStorage；所有 POST／DELETE／GET /api/profile 加 header `X-Player-Token`。收到 401 時（第 6 輪起不再有 403）提示「憑證遺失，請重新開始（新 ID）」或引導聯絡管理者刪資料。
2. 玩家 ID 改用 `crypto.getRandomValues` 產生，長度 ≥16 碼（後端下限 8）；刪除資料後換新 ID。
3. 錯誤判斷改用 `code`（例如 `locked`／`ended`），不要比對 error 文字。
4. 不要假設選項數為 2 或 3（3~4）。
5. too_painful 的「回到遊戲」流程：先顯示資源與確認，再送 `confirm:true`；處理 `cooldown`、`resume_limit` 的提示。
6. 玩家訊息可能是「（此訊息觸發安全提示，原文未保存）」，請照常顯示。
7. `safety.category="model"` 不會再出現；若前端有對應文案可移除。
8. 處理 429（`rate_limited`、`quota_exceeded`）的提示。


---
# 第 6 輪更新（以下與前文衝突時以本節為準）

## 授權回應統一（Q50 / Q52）
- 所有授權失敗（玩家不存在、沒帶 token、token 錯、沒有 token 的舊存檔）一律 **401 `unauthorized`、同一段訊息**，不再有 403 `forbidden`（code 保留但不會出現）。唯一例外：建檔型路由（start / nickname / consent / prefs）對「不存在的玩家」會直接建立並簽發 token。
- 因此 `GET /api/profile` 對新玩家也回 401：**前端沒有儲存 token 時不要呼叫 GET /api/profile**（視為新玩家，直接顯示首頁，之後 start 取得 token）。非建檔型路由（message / flag / review / resume / reset）對不存在的玩家回 401，不再是 `not_started`。
- 授權先於玩家級速率限制：未授權請求不會消耗該玩家的額度。另有來源 IP 級限制：每 IP 每分鐘 `GAME_RATE_PER_IP_MIN`（預設 300）個請求，超過 429 `rate_limited`；每 IP 每小時新建玩家 `GAME_NEW_PER_IP_HOUR`（預設 200，適合小組測試），超過 429 `quota_exceeded`（被拒時不留檔）。總量上限 `GAME_MAX_PLAYERS` 仍在，但單一來源無法灌滿。IP 取 TCP 來源位址；若放在反向代理後面，所有人會是同一個 IP，需先在代理層處理或調高限制。
- **舊存檔（沒有 token_hash）**：預設不可讀、不可寫、不可認領（一律 401）。處理方式：
  1. 管理者（伺服器設 `GAME_ADMIN_TOKEN`）呼叫 `POST /api/admin/migrate`，header `X-Admin-Token`，body `{player}` → 回 `{ok:true, token}`，由管理者把 token 交給原主；
  2. 或管理者用 `DELETE /api/profile?player=…` 加 `X-Admin-Token` 直接刪除；
  3. 或伺服器設 `GAME_ALLOW_LEGACY_CLAIM=1`，建檔型路由才允許認領（不建議，僅限封閉測試）。
  管理者 header 以 bytes 比對，非 ASCII 值回 401，不會 500；沒設 `GAME_ADMIN_TOKEN` 則管理者通道關閉。
- `saves/` 內既有 3 個舊檔未被動過，現在對外一律 401。

## 補標寬限（Q47）
- 劇情**自然結束**（`ended:true`，非安全終止）之後、**呼叫 `/api/review` 之前**，`POST /api/flag` 仍可使用（包含最後一則 NPC 訊息）。`review` 一旦成功（`state.reviewed`）或局因 safety 終止，flag 才回 400 `locked`。
- 為避免結束後偷看答案：**自然結束時 `red_flags` 不再自動公開**，只有「已檢舉的訊息」、GAME_DEV+reveal、或已結算／安全終止的局才會帶 `red_flags`。結算後請重新呼叫 `/api/start` 取得完整標示的 state（review 回應的 `coach.items` 本來就含答案）。
- 前端流程：局結束 → 顯示「最後確認：還有想補標的可疑訊息嗎？」→ 玩家按「看結算」→ `/api/review`。60 局情境（5 人格 × 12 種子）驗證：最佳策略（標出所有紅旗）recall 皆為 100%，不再被最後一則封頂。

## NPC 台詞（Q46 / Q49 / Q56）
- fallback 台詞只用該階段的 `mock_clean_lines`（無紅旗），沒有就用中性提示句；絕不取帶紅旗台詞。
- mock 每 3 回合固定 1 回合出正常台詞（位置由每局種子決定），同局不重複，該階段用完才回到一般台詞。
- 輸出過濾：NFKC＋去零寬後檢查；放行日期時間與一般數字；攔截全形網址、`dot com`、短網址、`@handle`、`k e v i n . m e`、電話（含零寬插入與中文數字）、帳號。

## 離開判斷（Q57）
`wants_leave`：「分手吧，才怪」「我朋友剛分手」「我們分手的話…」「我前任跟我分手過」「不要封鎖我」不算；「我要走了」「我走啦」「拜拜我先走」「別再聯絡了」算。

## 第二道 safety 分類器（Q48，預設關閉）
`GAME_SAFETY_LLM=1` 且 `GAME_LLM=claude` 時，server 啟動會嘗試把分類器注入 `safety.set_classifier`（後端 A 的介面）；介面不存在或非 claude 模式只印訊息、不影響運作。分類器未用真 API 實測。

## 前端需配合的變更（第 6 輪）
1. 沒有儲存 token 時不要呼叫 `GET /api/profile`；所有 401 一律視為「憑證無效／新玩家」處理（沒有 403；也不要依賴 `not_started` 區分，不存在的玩家一樣是 401）。
2. 局自然結束後先不要顯示答案：加一個「最後確認補標」步驟，按「看結算」才呼叫 `/api/review`；結算後再 `/api/start` 重新取得帶完整 `red_flags` 的 state。結算後不可再標旗（`locked`）。
3. 429 區分 `rate_limited`（稍後再試）與 `quota_exceeded`（目前無法建立新玩家）。
4. 舊使用者（localStorage 有舊 ID 但沒有 token）會被視為舊存檔而收到 401：請提示「請重新開始（產生新 ID）」，並不要自動重送原 ID 的建檔請求。


## 第 7 輪補充：教練 tone
- coach 訊息的 `tone` 有三種：`praise`（對方上一句有紅旗，玩家拒絕了）、`roast`（玩家順從）、**`neutral`**（玩家拒絕／清醒作答，但對方上一句其實沒有紅旗，教練不稱讚，改給中性提示，避免鼓勵過度警覺）。前端遇到 `neutral` 請用中性樣式顯示（不要用 👍 或 🔥），未知的 tone 一律當中性處理。
- 後端以 `coach.interject(..., has_red_flag=<對方上一句是否有紅旗>)` 傳遞；`_call_compat` 現在會在參數被略過時 log 警告（每個參數一次）。


## 第 8 輪補充：reviewed 與 phase
- 每個 State（start / message / resume 等）都有 `reviewed: bool` 與 `phase`：
  | phase | 條件 | 前端行為 |
  |---|---|---|
  | `playing` | 局未結束 | 正常聊天、可標旗 |
  | `final_check` | 自然結束且未結算 | 顯示「最後確認補標」，🚩 仍可用，按「看結算」才呼叫 /api/review；此時 `red_flags` 尚未公開 |
  | `locked` | 已結算（`reviewed:true`），或被 safety 終止（`reviewed:false`） | 不可標旗；已結算時 `red_flags` 全部公開 |
- `reviewed` 與 `phase` 不受玩家標旗數量、GAME_DEV reveal 影響；前端**不要再用「所有 NPC 訊息都帶 red_flags」推斷已結算**。
- 前端需配合：(1) 以 `state.phase` 決定畫面（取代自行推斷）；(2) `phase==="final_check"` 才顯示最後補標步驟；(3) `phase==="locked"` 時隱藏／停用 🚩；(4) review 成功後重新取得 state（/api/start）即可看到 `reviewed:true`、`phase:"locked"`。


## 最後一輪補充
- **錯誤憑證節流（Q64）**：每個「來源 IP」在 `GAME_AUTH_FAIL_WINDOW` 秒（預設 60）內授權失敗超過 `GAME_AUTH_FAIL_PER_IP`（預設 30）次，或同一「ID＋IP」超過 `GAME_AUTH_FAIL_PER_ID`（預設 10）次，之後的請求（含帶正確 token 的）直接回 429 `rate_limited`，視窗過後恢復。`/api/admin/migrate` 同樣受 IP 限速與失敗節流。0 代表關閉。
- **token 長度**：token 必須 16–256 字元，否則視為沒帶（401）。玩家 ID 最短 8 字元。
- **管理者動作稽核**：admin 的 migrate／delete 會寫 server log（只含 ID 雜湊前 8 碼，不含 token 與 ID）；啟動時若 `GAME_ADMIN_TOKEN` 少於 16 字元會警告。
- **存取 log 不再記錄 query string**（避免玩家 ID 進 log）。
- **預設值**：`GAME_NEW_PER_IP_HOUR` 預設 200；`GAME_MAX_PLAYERS` 預設 2000（小組測試遠低於此；要更大請調高）。
- 前端需配合：`quota_exceeded` 請顯示「目前無法建立新玩家，請聯絡測試主持人」；`rate_limited` 顯示「嘗試太頻繁，請稍後再試」。

- **教練 tone 渲染（Q67，與後端 A 對齊）**：`neutral` 與 `praise` 的文字現在相同（避免 tone 本身洩漏對方該句有沒有紅旗）。前端**必須把 `praise` 與 `neutral` 渲染成完全一樣**（同圖示、同顏色、同標題），否則 tone 就是答案。此項取代第 7 輪「neutral 用中性樣式」的建議。

## 情境小測驗（feature/quiz）

沿用 `X-Player-Token`、玩家鎖與寫入速率限制；先用既有同意流程建立玩家。以下均為 JSON POST，帶 `player`，未授權回 401。小測驗不呼叫 LLM，不改動遊戲清醒分數。

- `/api/quiz/state`：讀取 `active`、最近 20 次 `history`、累計 `completed_count`、`best_score`。
- `/api/quiz/start`：建立 6 題（5 題風險情境＋1 題正常對照）；已有未完成測驗則續答，不覆蓋。
- `/api/quiz/answer`：另帶 `attempt_id`、`question_id`、`choice`（從 0 起的整數索引）、`confidence`（1–3 整數）。依順序作答，每題確認後儲存並回傳解析；同一答案重試不重複計分，更改已確認答案回 400。分數由伺服器計算，不接受客戶端分數。

三個端點回傳相同狀態結構。`active.questions` 只有 `id`、`prompt`、`options`；已確認的解析位於 `active.answers`。完成後 `active` 增加 `score`、`completed_at`；之後再 start 才開始新測驗。題庫快照保存在玩家存檔，進行中的題目不受題庫更新影響。刪除玩家會一併刪除測驗資料。完整逐題解析保留於最近一次測驗，歷史僅保留時間與分數；累計次數與最佳分數不受 20 次上限影響。

## 我的成就（feature/achievements）

- `GET /api/achievements/catalog`：公開徽章條件，全部為未解鎖，不含任何玩家資料，也不建立玩家。
- `POST /api/achievements {player}`：沿用 token 驗證與速率限制，回傳 `badges`、`unlocked_count`、`total`、`newly_unlocked`。每枚徽章含 `id/title/description/icon/group/progress/target/unlocked/unlocked_at`。忽略客戶端指定的分數或解鎖狀態。
- 遊戲覆盤回應新增 `achievements`；小測驗完成時也在同一次存檔更新解鎖資料。解鎖時間只寫入一次，重新開始遊戲或測驗不清除徽章，刪除玩家時一併移除。
- 完成覆盤需至少有一次玩家回覆，安全提示中止的局不採計。紅旗徽章依精確數量，不採四捨五入的 precision/recall；守住荷包需愛情騙子局自然結束、曾遇金錢誘導且無轉款事件。
- `reviews[].achievement_stats` 保存必要的條件證據，讓角色局重置後仍能累積不同角色進度。舊存檔只回補仍保留的已覆盤局與既有測驗紀錄；缺乏證據的舊摘要不推測解鎖。舊紀錄回補日期為首次辨認成就的日期。
