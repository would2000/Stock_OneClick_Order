# Yuanta AutoTrading

這個專案用元大提供的 macOS arm64 Python SDK 測試自動交易 API。SDK 實際上是透過 `pythonnet` 載入 `.NET 8` 的 `YuantaSparkAPI.dll`，所以程式入口會先啟動 `coreclr`，再呼叫元大 API。

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

## FastAPI + React 當沖介面

目前已新增一版本機交易工作台：

```text
frontend/         React + TypeScript 操作介面
backend/app/      FastAPI 後端、風控、元大 API adapter
data/trading.db   本機 SQLite audit / kill switch 狀態
```

啟動後端：

```bash
cd /path/to/local/Desktop/Project/Stock_OneClick_Order
.venv/bin/python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

啟動前端：

```bash
cd /path/to/local/Desktop/Project/Stock_OneClick_Order/frontend
npm install
npm run dev
```

開啟：

```text
http://127.0.0.1:5173
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

實單仍有雙重防呆：`.env` 必須設定 `YUANTA_ENABLE_ORDER=YES`，且前端下單匣必須勾選「實單二次確認」。
「預覽」只做風控檢查、預估金額與 audit 紀錄，不會呼叫元大送單。

## 1. 安裝

需要 **Python 3.11** 與 **.NET 8 runtime**（`pythonnet` 載入元大 SDK 時需要）。clone 後在專案根目錄執行：

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

## 2. 填入帳密

`.env` 已經建立好，請直接編輯 `.env`，填入：

```text
YUANTA_ACCOUNT=你的元大帳號
YUANTA_PASSWORD=你的交易密碼
YUANTA_CERT_PATH=/path/to/local/Desktop/Project/Stock_OneClick_Order/YOUR_CERT.pfx
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

plist 範本放在 `scripts/launchd/`（`com.yuanta.trading.backend.plist`、`com.yuanta.trading.frontend.plist`，皆 `KeepAlive=true`）。

```bash
scripts/install-launchd.sh   # 複製 plist 到 ~/Library/LaunchAgents 並載入啟動
scripts/stop.sh              # 卸載 launchd 服務並清掉 8000/5173 殘留程序
```

**⚠️ macOS 權限前置作業（必要）**：本專案位於 `~/Desktop` 之下，macOS TCC 預設禁止 launchd 背景程序存取桌面資料夾，服務會以 `EX_CONFIG`(78) 失敗。二擇一：

1. 系統設定 → 隱私權與安全性 → 完整磁碟取用權，加入 `/bin/bash`（按 + 後以 Cmd+Shift+G 輸入路徑），然後重新執行 `scripts/install-launchd.sh`。
2. （較乾淨）把專案搬離 `~/Desktop`（例如 `~/Projects/`），並同步更新 `scripts/launchd/*.plist` 內的絕對路徑後再安裝。

注意：launchd 與 `scripts/dev.sh` 不要同時使用，會互搶 8000/5173 端口；切換前先執行 `scripts/stop.sh`。

### 驗證

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/health   # 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5173/             # 200
```

log 追蹤：`tail -f logs/uvicorn.log logs/vite.log`

## ⚖️ 免責聲明（Disclaimer）

- 本軟體以「**現狀**」（AS-IS）提供，**不附任何明示或默示擔保**，作者不對因使用本軟體所生之任何**交易損失、資金損失、資料毀損或其他損害**負責。詳見 [LICENSE](LICENSE)。
- 本軟體**並非投資建議**，亦不保證任何下單、報價、風控功能的正確性、即時性或可用性。
- 本軟體會對接**真實券商並可能送出真實委託**。使用者須自負風險，並對自己的帳號、憑證、密碼與所有下單行為**完全負責**。強烈建議先在**模擬環境**充分測試。
- 使用者須遵守所屬券商的 API 條款與當地金融法規。**券商 SDK 為券商專有，不隨本專案散佈，請自行向券商取得。**
- 繼續使用本軟體即表示你已理解並接受上述條款。
