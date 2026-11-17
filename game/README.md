# 醒醒吧！戀愛腦 — 遊戲原型

教育用文字 RPG：和不同依附／詐騙型態的 NPC 聊天，學著辨識紅旗。目前 AI 是 **mock 模式**（從 `../personas/*.md` 的台詞參考抽句，不花錢、不連網）。

## 需求

- **Python 3.9 以上**（實測 3.9.6：伺服器可啟動、全部測試通過）。只用標準函式庫，不需要安裝任何套件。
- 只有切換到 **Claude 模式**（`GAME_LLM=claude`）才需要 **Python 3.10 以上** 與 `pip install anthropic`，並設定 `ANTHROPIC_API_KEY`。這段程式碼**尚未用真的 API key 實測過**。
- 測試需要 `pytest`（`pip install pytest`）。
- 一次裝好測試與 Claude 模式所需套件：`python3 -m venv ../.venv && source ../.venv/bin/activate && pip install -r requirements.txt`（需 Python 3.10+）。

## 啟動

```bash
cd game
python3 server.py                 # 打開 http://localhost:8000
GAME_DEV=1 python3 server.py      # 開發者模式（開發面板、看實際 prompt、顯示隱藏紅旗）
python3 -m pytest -q tests        # 跑測試
```

> **目錄依賴**：遊戲會讀上層資料夾的 `../personas/*.md`（人格 prompt，由 Prompt 組維護）。只複製 `game/` 會在啟動時直接報錯並列出缺失檔案，請連同 `personas/` 一起搬。

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `PORT` | 8000 | 伺服器埠號 |
| `GAME_DEV` | 未設 | `1` 才開放 `reveal`、`hour`、`GET /api/prompt`（開發用，正式測試不要開） |
| `GAME_LLM` | `mock` | `claude` 啟用 Claude API（需 Python 3.10+、`anthropic`、`ANTHROPIC_API_KEY`） |
| `GAME_CLAUDE_MODEL` | 見 `engine/llm.py` | 換模型 |
| `GAME_SAFETY_LLM` | Claude 模式下預設啟用；`0` 關閉 | 第二道 safety 分類器（玩家文字會送到外部 LLM；同意文字 v2 已說明；**未用真 API 實測**）。mock 模式沒有 LLM，不適用 |
| `GAME_ADMIN_TOKEN` | 未設（管理者通道關閉） | 管理者金鑰，用於 `POST /api/admin/migrate` 與 `DELETE /api/profile`（header `X-Admin-Token`）。請用 16 字元以上隨機字串 |
| `GAME_ALLOW_LEGACY_CLAIM` | 未設 | `1` 才允許沒有 token 的舊存檔被認領（不建議） |
| `GAME_RETENTION_DAYS` | 0（不清理） | 啟動時刪除超過 N 天沒更新的存檔 |
| `GAME_REQUIRE_TOKEN` | 1 | `0` 關閉 token 驗證（僅測試用） |
| `GAME_MIN_ID_LEN` | 8 | 玩家 ID 最短長度 |
| `GAME_MAX_PLAYERS` | 2000 | 玩家存檔總量上限 |
| `GAME_NEW_PER_IP_HOUR` | **200** | 每個來源 IP 每小時可新建的玩家數 |
| `GAME_RATE_PER_MIN` | 60 | 每位玩家每分鐘寫入請求數 |
| `GAME_RATE_PER_IP_MIN` | 300 | 每個來源 IP 每分鐘請求數 |
| `GAME_AUTH_FAIL_PER_IP` / `GAME_AUTH_FAIL_PER_ID` / `GAME_AUTH_FAIL_WINDOW` | 30 / 10 / 60 秒 | 錯誤憑證嘗試節流，超過回 429 |
| `GAME_RESUME_COOLDOWN` | 600 秒 | too_painful 後重複觸發時暫不可回到遊戲的冷卻時間 |
| `GAME_QUIET` | 未設 | `1` 關閉存取 log |

**小組／教室測試**：同一個 Wi-Fi、ngrok 或反向代理後，所有人會共用同一個來源 IP（伺服器看的是 TCP 來源位址，不讀 `X-Forwarded-For`）。預設的 `GAME_NEW_PER_IP_HOUR=200` 對小組足夠；人數更多請調高，否則第 N+1 位會看到「目前無法建立新玩家」（`quota_exceeded`）。

## 遊戲怎麼玩

1. 選對象（5 種人格，可選男／女）
2. 用選項或自己打字回覆；看到可疑訊息點旁邊的 🚩 檢舉（正常的訊息不要亂標，誤檢舉會扣分）
3. 教練會依你選的尺度（預設溫柔）給回饋；可靜音
4. 劇情 5 個階段；局結束後有「最後確認補標」步驟，再按結算看清醒分數與逐句覆盤
5. 切換對象再切回來，對話會接著（存在 `saves/<玩家ID>.json`）；換新對象時，暱稱與玩家自述的年齡會帶進 NPC prompt，不用重新自我介紹

## token 與隱私

- 玩家第一次建立資料時，伺服器簽發隨機 token（只存 SHA-256 雜湊），之後所有寫入與讀取都要帶 `X-Player-Token`。token 遺失無法找回，換一個新 ID 重新開始；舊資料由管理者刪除或保存期限清理。
- 沒有 token 的**舊存檔**預設不可讀寫；只能由管理者遷移／刪除。
- 對話與暱稱以明文 JSON 存在 `saves/`（已列入 `.gitignore`）。觸發安全規則的玩家原文**不入庫**（只留類別與時間）。玩家可用「刪除我的資料」（`DELETE /api/profile`）刪除全部資料。
- 存取 log 不記錄 query string。接 Claude API 時，玩家文字會送到 Anthropic，同意文字須如實告知。
- 同意紀錄可用 `POST /api/consent` 存到後端（只記錄，不強制）。

## 安全限制（請務必先讀）

**本遊戲不是危機介入工具，目前的 safety 機制不能偵測多數危機表達；使用者測試時必須有人在場。** 詳細說明與驗證結果見 [`docs/safety_limits.md`](docs/safety_limits.md)。🆘 求助入口在所有畫面都可點。

## 目錄結構

| 路徑 | 內容 |
|---|---|
| `server.py` | HTTP 伺服器（標準函式庫），API 契約見 `docs/api_contract.md` |
| `engine/game.py` | 主流程與劇情狀態機、token 授權 |
| `engine/store.py` | 玩家存檔（每玩家一把鎖、原子寫入、損毀隔離） |
| `engine/llm.py` | `MockLLM` / `ClaudeLLM`、輸出驗證與 fallback |
| `engine/personas.py` | 讀 `../personas/*.md` 並與 `data/personas.json` 合併 |
| `engine/safety.py`、`scoring.py`、`coach.py` | 安全規則、計分、教練 |
| `data/personas.json` | NPC 名字、玩家選項、mock 台詞設定 |
| `static/` | 網頁介面 |
| `saves/` | 玩家存檔（不入版控） |
| `tests/` | pytest 測試 |
| `docs/` | 契約、會議紀錄、問題清單、研究文件 |

## 使用者測試前檢查清單

- [ ] 不要設 `GAME_DEV`；確認 `GAME_ADMIN_TOKEN` 已設（16 字元以上）並妥善保管
- [ ] `GAME_NEW_PER_IP_HOUR` 大於受測人數
- [ ] **`saves/` 內仍有早期開發的舊存檔（含暱稱與對話）。這些檔案不要自動刪除，請由負責人確認後人工搬走或清空**；在確認前它們對外一律回 401（不可讀寫）
- [ ] 同意文字已填入保存天數與聯絡信箱；已取得受測者同意（IRB／倫理審查）
- [ ] 現場有人在場，並已告知求助資源（1925、165、113）
- [ ] `python3 -m pytest -q tests` 全過
- [ ] 若啟用 Claude 模式（safety 第二道預設隨之啟用）：同意文字 v2 已說明外部處理，且**必須先用真 API 與盲測集實測**（目前尚未做）

## 已知限制

- Claude 模式與 safety 第二道分類器尚未用真 API 實測；mock 的台詞數量有限，重玩會重複。
- safety 是規則式，召回有限（見 `docs/safety_limits.md`）；計分公式為暫定版。
- 單一 process 的鎖：多 worker 部署會失效，需改 SQLite 或檔案鎖。
- 來源 IP 限制不讀 `X-Forwarded-For`。介面只做網頁版，不做 LINE Bot（2026-11-09 決定）。
- 玩家 token 遺失無法找回。

## 情境小測驗

首頁同意資料說明、進入遊戲後，點「小測驗」即可練習。每次從 12 題題庫抽 6 題（含 1 題正常互動），選答案及把握程度，確認後看解析。進度逐題自動儲存，重新整理後可續答；完成後可查看本次逐題解析、最近 20 次成績與歷史最佳分數。分數與遊戲清醒分數分開，不用來判定依附類型或受騙機率。

題庫：`data/quiz.json`；後端：`engine/quiz.py`；前端：`static/quiz.js`；測試：`tests/test_quiz.py`。題庫只由後端讀取，作答前不傳標準答案。沿用既有 token 與刪除資料機制，不需新增套件或資料庫。

## 我的成就

首頁、角色選單與覆盤頁均可開啟「我的成就」。未同意／未開始的玩家可先瀏覽徽章條件；開始後會顯示自己的解鎖紀錄，可篩選全部、已解鎖與未解鎖。8 枚徽章涵蓋覆盤、精準辨識、五種角色、金錢界線、重新選擇及小測驗，條件在每張卡片中完整列出。成就由後端判定與保存，不另外要求套件。

本分支接續 `feature/quiz`，包含小測驗及成就；成就獨立變更可用 `git diff feature/quiz..feature/achievements` 檢視。先合併小測驗 PR，再將成就分支同步至最新 main 後開成就 PR。不要直接覆蓋已有組員修改的專案。

驗證：`python3 -m pytest -q tests`。相關檔案：`engine/achievements.py`、`static/achievements.js`、`tests/test_achievements.py`。瀏覽器人工檢查：手機窄螢幕、深淺色模式、鍵盤 Tab／Escape、完成遊戲或測驗後再開啟成就、重整後解鎖狀態保留。
