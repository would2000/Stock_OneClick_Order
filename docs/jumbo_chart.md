# 江波圖完整架構

## 1. 功能目標

本功能用來建立台股江波走勢圖 / 類江波走勢圖，提供看盤介面、策略訊號驗收與盤中市場廣度觀察使用。

前端以 Apache ECharts 繪製多區塊分時走勢圖，目前包含：

1. 委買筆數 / 委賣筆數 / 成交筆數
2. 委買張數 / 委賣張數 / 成交張數
3. 漲家數 / 跌家數 / 平盤家數
4. 每筆委買 / 每筆委賣 / 每筆成交平均張數

圖表支援 tooltip、同步十字線、legend scroll、dataZoom 縮放與拖曳時間區間。

## 2. 前端檔案

- `frontend/src/charts/jumboChartOption.ts`
  - 建立 ECharts option。
  - 定義 `JumboPoint` 型別。
  - 匯出 `buildJumboChartOption(data)`。

- `frontend/src/components/JumboChart.tsx`
  - React 圖表元件。
  - 使用 `echarts-for-react`。
  - props: `data`, `height`。
  - 不直接 fetch 後端資料。

- `frontend/src/adapters/jumboDataAdapter.ts`
  - 將後端或本地 raw JSON 正規化成 `JumboPoint[]`。
  - 支援欄位別名、時間格式轉換、數字轉型、缺欄位檢查與排序。

- `frontend/src/services/jumboDataService.ts`
  - 提供 `fetchJumboData(params)`。
  - 從後端取得 raw data，再呼叫 `normalizeJumboData(rawData)`。

- `frontend/src/pages/JumboChartPage.tsx`
  - 真資料江波圖頁面。
  - 提供 market、date、reload 控制。
  - 路徑：`http://127.0.0.1:5173/jumbo-chart`

## 3. 後端 API

```text
GET /api/jumbo-data?market=TSE&date=YYYY-MM-DD
```

參數：

- `market`: `TSE` 或 `OTC`
- `date`: `YYYY-MM-DD`

回傳：

- JSON array
- 若找不到任何資料，回傳 `[]`

## 4. 後端雙來源規則

後端目前採雙來源 provider 架構，不破壞既有 JSON fixture/cache 功能。

當 `date` 是今天：

1. 先嘗試讀取 realtime / today / cache / minute / kbar_1m 類本機來源。
2. 若來源有真實江波欄位，直接正規化成前端 adapter 可接受格式。
3. 若來源只有 minute OHLCV，產生 synthetic jumbo / 類江波圖。
4. synthetic jumbo 中，委買 / 委賣相關欄位維持 `0`，不假造真實委買委賣資料。
5. 若本機即時來源讀不到或沒有可用資料，fallback 到 `data/jumbo/*.json`。

當 `date` 不是今天：

1. 不嘗試 realtime provider。
2. 直接讀 JSON fixture/cache。

若 realtime provider 與 JSON fixture/cache 都沒有資料：

- 回傳 `[]`。

## 5. JSON 檔案位置

後端 JSON file provider 會依序尋找以下檔案：

```text
data/jumbo/TSE_YYYY-MM-DD.json
data/jumbo/TSE_YYYYMMDD.json
data/jumbo/TSE/YYYY-MM-DD.json
data/jumbo/TSE/YYYYMMDD.json
```

`OTC` 同理：

```text
data/jumbo/OTC_YYYY-MM-DD.json
data/jumbo/OTC_YYYYMMDD.json
data/jumbo/OTC/YYYY-MM-DD.json
data/jumbo/OTC/YYYYMMDD.json
```

檔案內容可為 JSON array，或包含 `data` / `rows` / `records` / `items` 的物件。

## 6. 匯出工具

工具位置：

```text
scripts/export_jumbo_json.py
```

使用範例：

```bash
.venv/bin/python scripts/export_jumbo_json.py --market TSE --date 2026-06-10
```

指定輸出位置：

```bash
.venv/bin/python scripts/export_jumbo_json.py \
  --market OTC \
  --date 2026-06-10 \
  --out data/jumbo/OTC_2026-06-10.json
```

指定本地資料來源：

```bash
.venv/bin/python scripts/export_jumbo_json.py \
  --market TSE \
  --date 2026-06-10 \
  --source-root /path/to/local/market/data
```

預設輸出：

```text
data/jumbo/{MARKET}_{YYYY-MM-DD}.json
```

若當日無資料，工具會輸出 `[]`，不會中斷。

## 7. Smoke Fixture

目前已建立 smoke test fixture：

```text
data/jumbo/TSE_2026-06-10.json
```

內容：

- 271 rows
- 時間範圍：09:00 到 13:30
- 每 1 分鐘一筆
- 欄位符合 `normalizeJumboData`
- 數值有早盤波動、盤中收斂、尾盤放大的 mock 型態

## 8. 驗收指令

後端編譯檢查：

```bash
.venv/bin/python -m compileall backend
```

前端 build 驗證：

```bash
cd frontend
npm run build
```

確認後端資料 API：

```bash
curl 'http://127.0.0.1:8000/api/jumbo-data?market=TSE&date=2026-06-10'
```

開啟前端頁面：

```text
http://127.0.0.1:5173/jumbo-chart
```

## 9. 注意事項

synthetic jumbo / 類江波圖不是完整券商定義的江波圖。若來源只有分鐘 OHLCV，只能推導成交量、漲家數、跌家數、平盤家數與每筆成交平均張數等近似資訊。

只有來源本身具備真實委買、委賣、成交統計欄位時，才是完整 real jumbo，例如：

- 委買筆數
- 委賣筆數
- 成交筆數
- 委買張數
- 委賣張數
- 成交張數
- 漲家數
- 跌家數
- 平盤家數
- 每筆委買
- 每筆委賣
- 每筆成交平均張數
