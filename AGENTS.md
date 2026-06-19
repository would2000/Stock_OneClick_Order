# AGENTS.md — AI 協助安裝與使用劇本

> 這份文件是寫給 **AI 程式助理**（Claude Code、Cursor、Copilot 等）看的。
> 當一位新使用者把這個 repo clone 下來、請你「幫我把這個程式裝起來並跑起來」時，
> 請**照本文件逐步引導他**。使用者多半不是工程師，請用白話、一次一步、每步等他完成再繼續。

---

## 0. 這是什麼程式（先讓使用者知道風險）

這是一套**本機**的台股當沖下單工作台：FastAPI 後端 + React 前端，透過元大證券（或永豐金 Shioaji）API 下單，並提供一個**純本機模擬沙盒**可無風險練習。

⚠️ **這會碰到真實金錢。** 在引導過程中你（AI）必須遵守下列鐵則：

1. **絕不**主動開啟實單。保持 `.env` 的 `YUANTA_ENV=UAT`、`YUANTA_ENABLE_ORDER=NO`，直到使用者**明確**要求且已完成驗證。
2. **絕不**把使用者的機密（`.env`、`frontend/.env`、`*.pfx`、API 金鑰、帳號密碼）印到對話、貼到網路、或 `git add` / commit。
3. **絕不**幫使用者捏造券商帳號或憑證——這些只能由他本人向券商申請。
4. 本 repo **不含**券商 SDK；你要引導使用者自行下載（見第 3 步）。
5. 任何「送單」「連線正式環境」「改 `ENABLE_ORDER`」的動作，先用一句話**複述後果並請他確認**，再執行。
6. **本程式只設計給本機使用（前後端皆綁 `127.0.0.1`）。絕不要把後端改成 `--host 0.0.0.0` 或對外暴露**。loopback 流量不出本機、不需 TLS；一旦對外開放，帳密／`API_KEY`／下單內容會以明文在網路上傳。若使用者真的要遠端使用，請改用 SSH 通道，或在前面加 HTTPS 反向代理（Caddy/nginx）並改用 `wss`，**切勿裸奔**。

建議先讓使用者**只玩模擬環境**（不需任何帳密/憑證/SDK 也能跑前端＋模擬下單），熟悉後再接真實券商。

---

## 1. 先確認環境（請 AI 主動偵測並回報）

請執行並回報結果，再決定後續指令：

```bash
python3.11 --version    # 需要 Python 3.11.x
node --version          # 前端需要 Node 20+
npm --version
uname -sm               # 作業系統與架構（mac: Darwin arm64 / x86_64；Windows 改用 PowerShell）
```

- macOS 沒有 `python3.11`：建議 `brew install python@3.11`。
- Windows：到 python.org 安裝 3.11，並安裝 Node 20+；用 PowerShell 執行對應指令（把 `.venv/bin/` 換成 `.venv\Scripts\`）。

---

## 2. 安裝相依套件

優先使用 repo 內的一鍵安全腳本（會自動建立 `.env` / `frontend/.env`、產生一致的本機 `API_KEY`，並維持 UAT / 不開單）：

```bash
scripts/bootstrap.sh
```

若使用者明確要你裝好後直接啟動模擬環境，可用：

```bash
scripts/bootstrap.sh --start
```

腳本完成後仍要依第 5 步驗證前後端。如果腳本失敗，才改用下列手動指令逐步處理：

```bash
# 後端：建立虛擬環境並安裝
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

# .NET 8 runtime（pythonnet 載入元大 SDK 用）。擇一：
#   官方下載：https://dotnet.microsoft.com/download/dotnet/8.0
#   或裝到專案內：
curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 8.0 --runtime dotnet --install-dir ./.dotnet

# 前端套件
npm --prefix frontend install
```

---

## 3. 下載券商 SDK（接真實券商才需要；只玩模擬可略過）

元大 SDK 屬元大專有、**不在本 repo 內**。請引導使用者：

1. 登入元大證券 API 服務，下載**對應其作業系統/架構**的 **Python 版** SDK。
2. 解壓到專案根目錄，資料夾命名為 `YuantaSparkAPI_<平台>_Python/`：
   - macOS Apple Silicon → `YuantaSparkAPI_osx-arm64_Python/`
   - Windows x64 → `YuantaSparkAPI_win-x64_Python/`（實際名稱以元大壓縮檔為準）

> ✅ **路徑會自動偵測**：程式（[`backend/app/yuanta/client.py`](backend/app/yuanta/client.py) 與 [`yuanta_smoke_test.py`](yuanta_smoke_test.py)
> 的 `resolve_sdk_dir()`）會依此順序找 SDK 資料夾：
> 1. 環境變數 `YUANTA_SDK_DIR`（最高優先，可指向任意路徑）；
> 2. 依 OS/架構推測的慣用名（`osx-arm64` / `osx-x64` / `win-x64` / `linux-x64`）；
> 3. 後備：專案根目錄中任何符合 `YuantaSparkAPI_*_Python` 的資料夾。
>
> 所以只要使用者把 SDK 解壓成 `YuantaSparkAPI_*_Python/`，**任何平台都會自動命中**；名稱特殊時，請他在 `.env` 加 `YUANTA_SDK_DIR=/絕對路徑` 指定即可。

永豐金（Shioaji）的 SDK 是 **PyPI 套件**（不像元大要下載 DLL），裝在 venv 即可。只有要接永豐時才需要，請使用**選用相依檔**：

```bash
.venv/bin/python -m pip install -r requirements-sinopac.txt   # 內含 shioaji
```

接永豐還需準備永豐的憑證（`.pfx`/CA）與 API key，填到 `.env` 的 `SHIOAJI_*` 欄位。只接元大的使用者可整段略過。

---

## 4. 填入設定（每位使用者填自己的）

```bash
cp .env.example .env                    # 後端設定
cp frontend/.env.example frontend/.env  # 前端設定
```

請逐項引導使用者填 `.env`：

| 欄位 | 說明 |
| --- | --- |
| `YUANTA_ACCOUNT` / `YUANTA_PASSWORD` | 元大帳號/交易密碼（只玩模擬可留空） |
| `YUANTA_CERT_PATH` | 憑證 `.pfx` 路徑，**請放在專案資料夾外**避免誤上傳 |
| `YUANTA_CERT_PASSWORD` | 憑證密碼 |
| `YUANTA_ENV` | 先維持 `UAT`（測試）。**不要**擅自改 `PROD` |
| `YUANTA_ENABLE_ORDER` | 先維持 `NO`。驗證完才由使用者改 `YES` |
| `API_KEY` | 保護敏感端點。用下面指令產生一組 |
| `FUGLE_API_KEY` | 富果報價金鑰（選填，模擬環境用真實行情）｜申請：developer.fugle.tw |

產生 `API_KEY` 並讓**前後端填同一個值**（這是常見地雷）：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# 把輸出同時填到 .env 的 API_KEY= 與 frontend/.env 的 VITE_API_KEY=
```

> 🔑 **前端 `VITE_API_KEY` 必須等於後端 `API_KEY`**，否則所有下單/連線/風控端點都會回 403。
> 改完任一個都要**重啟對應服務**才生效。

---

## 5. 啟動

```bash
# macOS / Linux：一鍵啟動前後端（背景，log 寫到 logs/）
scripts/dev.sh

# 或手動分開啟：
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000   # 後端
npm --prefix frontend run dev                                                  # 前端
```

啟動後開瀏覽器：**http://127.0.0.1:5173**

驗證兩端：

```bash
curl -s -o /dev/null -w "backend  %{http_code}\n" http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "frontend %{http_code}\n" http://127.0.0.1:5173/
```

停止：`scripts/stop.sh`（或 kill 佔用 8000/5173 的程序）。

---

## 6. 接真實券商前的安全驗證（請依序，全部通過才談實單）

```bash
.venv/bin/python yuanta_smoke_test.py login     # 只測登入
.venv/bin/python yuanta_smoke_test.py quote     # 查報價
.venv/bin/python yuanta_smoke_test.py summary   # 查庫存
```

三項都正常後，**由使用者自己**決定是否把 `.env` 改 `YUANTA_ENABLE_ORDER=YES`；送單仍需命令列加 `--confirm-send-order`，前端送單也需勾「實單二次確認」。請 AI 在每個開啟實單的步驟前複述風險並請使用者確認。

---

## 7. 模擬沙盒說明

- 登入時環境選「模擬」即可，**不需任何帳密/憑證/SDK**。
- 模擬的**庫存/委託/成交會保存在本機 `data/trading.db`，可跨重啟與重新登入保留**（像一個持久的模擬帳戶）。
- 報價在有 `FUGLE_API_KEY` 時用真實行情，否則退回合成報價（仍可練下單）。

---

## 8. 疑難排解（常見）

| 症狀 | 處理 |
| --- | --- |
| 下單/連線端點回 **403** | `frontend/.env` 的 `VITE_API_KEY` 與 `.env` 的 `API_KEY` 不一致，或改後沒重啟。對齊後重啟兩端。 |
| 後端起不來、`address already in use` | 8000 被占。先 `scripts/stop.sh` 或 kill 佔用程序再啟。 |
| `pythonnet` / `coreclr` 載入失敗 | 沒裝 .NET 8 runtime，或 SDK 資料夾名稱/路徑不符（見第 3 步的已知限制）。 |
| 找不到 `YuantaSparkAPI` | 沒下載 SDK，或資料夾名稱與程式寫死的 `osx-arm64` 不符。 |
| `shioaji` import 失敗 | 尚未 `pip install shioaji`（只接元大可忽略）。 |

---

## 9. 給 AI 的收尾檢查清單

引導完成後，請確認並回報：

- [ ] `python -c "import sqlite3"` 可用；`data/trading.db` 會在首次啟動自動建立。
- [ ] `/api/health` 回 200，且 `yuanta_env` 與 `orders_enabled` 是使用者**預期**的值（預設應為 UAT / false）。
- [ ] **沒有**任何機密被印出或被 `git add`（檢查 `git status` 不應出現 `.env`、`frontend/.env`、`*.pfx`、`YuantaSparkAPI_*`）。
- [ ] 提醒使用者：實單有風險、盈虧自負，本程式 AS-IS 無擔保（見 `LICENSE`）。
