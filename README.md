# Stock OneClick Order

本專案是一套**本機使用**的台股一鍵下單工作台：FastAPI 後端 + React 前端，支援純本機模擬沙盒，也可在使用者自行準備券商帳號、憑證與 SDK 後連接元大證券或永豐金 Shioaji。

## ⚠️ 開源使用前必讀（SDK 與機密設定）

本 repo **不包含**任何券商 SDK，也**不包含**任何個人帳密／憑證——這些都已在 `.gitignore` 排除，不會出現在公開原始碼裡。每位使用者需自行準備下列四項：

1. **券商帳號**：你需要有自己的元大證券（或永豐金）帳號、API 開通與憑證。
2. **下載券商 SDK（必要）**：元大 SDK 屬元大專有、受授權限制，**不可隨原始碼散佈**。請登入元大 API 服務，下載**對應你作業系統／架構**的 Python SDK，解壓到專案根目錄並命名為 `YuantaSparkAPI_<平台>_Python/`，例如：
   - macOS Apple Silicon → `YuantaSparkAPI_osx-arm64_Python/`
   - Windows x64 → `YuantaSparkAPI_win-x64_Python/`（名稱依元大提供的壓縮檔為準）
3. **填入機密設定**：複製範本後填入你自己的帳密與金鑰——
   ```bash
   cp .env.example .env                      # 後端：元大/永豐帳密、API_KEY、Fugle 金鑰
   cp frontend/.env.example frontend/.env    # 前端：VITE_API_KEY（須與後端 API_KEY 相同）
   ```
4. **憑證 `.pfx`**：放在**專案資料夾之外**（避免誤上傳），並讓 `.env` 的 `YUANTA_CERT_PATH` 指向該路徑。

> 🔒 安全預設：`.env.example` 預設 `YUANTA_ENV=UAT`、`YUANTA_ENABLE_ORDER=NO`。在 `login`／`quote`／`summary` 都驗證正常前，請勿開啟實單。完整步驟見下方「安裝」章節。

## AI 一鍵安裝啟動

如果你不是工程師，最簡單的方式是把本 repo clone 下來後，對 AI 程式助理說：

```text
請閱讀 AGENTS.md，照它的安全規則幫我安裝並啟動這個專案。先只跑模擬環境，不要開實單。
```

AI 可以執行這個安全預設的一鍵腳本：

```bash
scripts/bootstrap.sh --start
```

它會自動建立 `.venv`、安裝 Python / frontend 套件、安裝專案內 `.dotnet` runtime、建立 `.env` 與 `frontend/.env`，並產生前後端一致的本機 `API_KEY`。預設仍是 `YUANTA_ENV=UAT`、`YUANTA_ENABLE_ORDER=NO`。

啟動後開啟：

```text
http://127.0.0.1:5173
```

只安裝不啟動：

```bash
scripts/bootstrap.sh
```

停止本機服務：

```bash
scripts/stop.sh
```

## FastAPI + React 當沖介面

目前已新增一版本機交易工作台：

```text
frontend/         React + TypeScript 操作介面
backend/app/      FastAPI 後端、風控、元大 API adapter
data/trading.db   本機 SQLite audit / kill switch 狀態
```

第一版 API：

```text
GET  /api/health
GET  /api/yuanta/status
POST /api/yuanta/connect
POST /api/yuanta/disconnect
GET  /api/candidates/today
GET  /api/quotes?symbols=2885,2330
GET  /api/positions
POST /api/orders/preview
POST /api/orders/send
GET  /api/risk/kill-switch
POST /api/risk/kill-switch
```

券商登入只負責連線，不會在程式內把環境切成 PROD，也不會自動開啟下單總開關。
實單仍有雙重防呆：`.env` 必須設定 `YUANTA_ENABLE_ORDER=YES`，且前端下單匣必須勾選「實單二次確認」。
「預覽」只做風控檢查、預估金額與 audit 紀錄，不會呼叫元大送單。

## 1. 手動安裝

需要 **Python 3.11**、**Node 20+** 與 **.NET 8 runtime**（`pythonnet` 載入元大 SDK 時需要）。clone 後在專案根目錄執行：

```bash
# 1) 建立虛擬環境並安裝 Python 相依
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

# 2) 安裝 .NET 8 runtime（擇一）：
#    - 官方安裝：https://dotnet.microsoft.com/download/dotnet/8.0
#    - 或用官方腳本裝到專案內 ./.dotnet：
#      curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 8.0 --runtime dotnet --install-dir ./.dotnet
```

> Windows 使用者請改用對應的 PowerShell 指令，並確認 SDK 下載的是 Windows 版（見上方「開源使用前必讀」）。

> 接**永豐金（Shioaji）**才需要的選用相依：`.venv/bin/python -m pip install -r requirements-sinopac.txt`（只接元大可略過）。元大 SDK 不在 PyPI，需另行向元大下載 DLL（見「開源使用前必讀」第 2 點）。

## 2. 填入帳密

若未使用 `scripts/bootstrap.sh`，請先建立設定檔：

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

把產生的同一組金鑰填到 `.env` 的 `API_KEY=` 與 `frontend/.env` 的 `VITE_API_KEY=`。

只跑模擬沙盒可不填券商帳密。要接元大時，請編輯 `.env`，填入：

```text
YUANTA_ACCOUNT=你的元大帳號
YUANTA_PASSWORD=你的交易密碼
YUANTA_CERT_PATH=/path/outside/repo/your-yuanta-cert.pfx
YUANTA_CERT_PASSWORD=你的憑證密碼
YUANTA_ENV=UAT
```

先保留：

```text
YUANTA_ENABLE_ORDER=NO
```

## 3. 安全測試

只測登入：

```bash
.venv/bin/python yuanta_smoke_test.py login
```

查報價：

```bash
.venv/bin/python yuanta_smoke_test.py quote
```

查庫存：

```bash
.venv/bin/python yuanta_smoke_test.py summary
```

查 K 線：

```bash
.venv/bin/python yuanta_smoke_test.py kline
```

## 4. 預覽現貨下單

先在 `.env` 設定下單內容：

```text
YUANTA_ORDER_SYMBOL=2885
YUANTA_ORDER_SIDE=B
YUANTA_ORDER_PRICE=35.0
YUANTA_ORDER_QTY=1
YUANTA_ORDER_PRICE_FLAG=M
YUANTA_ORDER_TYPE=0
YUANTA_ORDER_TRADE_KIND=0
YUANTA_ORDER_AP_CODE=0
YUANTA_ORDER_TIME_IN_FORCE=0
```

預覽，不會登入也不會送單：

```bash
.venv/bin/python yuanta_smoke_test.py order-preview
```

## 5. 送出現貨下單

確認 `login`、`quote`、`summary` 都正常後，才把 `.env` 改成：

```text
YUANTA_ENABLE_ORDER=YES
```

送單時還必須在命令列加上確認參數：

```bash
.venv/bin/python yuanta_smoke_test.py send-stock-order --confirm-send-order
```

如果少了 `YUANTA_ENABLE_ORDER=YES` 或少了 `--confirm-send-order`，程式只會顯示預覽並拒絕送單。

## 6. 開發服務常駐（backend:8000 / frontend:5173）

### 一次性啟動（手動）

```bash
scripts/dev.sh
```

會先 kill 佔用 8000/5173 的舊程序，再背景啟動：

- 後端：`.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000` → `logs/uvicorn.log`
- 前端：`cd frontend && npm run dev` → `logs/vite.log`

### launchd 常駐（崩潰/誤殺自動重啟）

`scripts/install-launchd.sh` 會依目前 clone 路徑動態產生 launchd plist（皆 `KeepAlive=true`），不需要手動改絕對路徑。

```bash
scripts/install-launchd.sh   # 複製 plist 到 ~/Library/LaunchAgents 並載入啟動
scripts/stop.sh              # 卸載 launchd 服務並清掉 8000/5173 殘留程序
```

**⚠️ macOS 權限前置作業（必要）**：本專案位於 `~/Desktop` 之下，macOS TCC 預設禁止 launchd 背景程序存取桌面資料夾，服務會以 `EX_CONFIG`(78) 失敗。二擇一：

1. 系統設定 → 隱私權與安全性 → 完整磁碟取用權，加入 `/bin/bash`（按 + 後以 Cmd+Shift+G 輸入路徑），然後重新執行 `scripts/install-launchd.sh`。
2. （較乾淨）把專案搬離 `~/Desktop`（例如 `~/Projects/`）後再安裝。

注意：launchd 與 `scripts/dev.sh` 不要同時使用，會互搶 8000/5173 端口；切換前先執行 `scripts/stop.sh`。

### 驗證

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/health   # 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5173/             # 200
```

log 追蹤：`tail -f logs/uvicorn.log logs/vite.log`

## 🔒 本機安全（請勿對外暴露）

本程式**只設計給本機使用**：後端綁 `127.0.0.1`、前端綁 `127.0.0.1`、CORS 僅允許 localhost。這段前後端流量不離開你的電腦，因此**不需要 TLS/HTTPS 加密**；同機威脅（其他程序、惡意網頁 CSRF）則由「loopback 綁定 + `X-API-Key` + CORS 白名單」防護。

⚠️ **請勿把後端改成 `--host 0.0.0.0` 或以任何方式對外開放（區網／遠端／port forward／反向代理／雲端）。** 一旦跨出 localhost，帳號密碼、`API_KEY` 與下單內容會以**明文**在網路上傳。若真的需要遠端使用，務必：

- 改用 **SSH 通道**（`ssh -L 8000:127.0.0.1:8000 ...`），或
- 在前面架 **HTTPS 反向代理**（如 Caddy／nginx）並把 WebSocket 改用 `wss`。

> 註：與券商（元大／永豐）和富果的連線走外網，但那是由它們的 SDK／HTTPS 負責加密，與本機前後端這段無關。

## ⚖️ 免責聲明（Disclaimer）

- 本軟體以「**現狀**」（AS-IS）提供，**不附任何明示或默示擔保**，作者不對因使用本軟體所生之任何**交易損失、資金損失、資料毀損或其他損害**負責。詳見 [LICENSE](LICENSE)。
- 本軟體**並非投資建議**，亦不保證任何下單、報價、風控功能的正確性、即時性或可用性。
- 本軟體會對接**真實券商並可能送出真實委託**。使用者須自負風險，並對自己的帳號、憑證、密碼與所有下單行為**完全負責**。強烈建議先在**模擬環境**充分測試。
- 使用者須遵守所屬券商的 API 條款與當地金融法規。**券商 SDK 為券商專有，不隨本專案散佈，請自行向券商取得。**
- 繼續使用本軟體即表示你已理解並接受上述條款。
