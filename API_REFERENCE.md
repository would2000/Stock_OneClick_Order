# Yuanta Spark API Reference

本文件整理本專案在 macOS arm64 + Python 上使用元大 Spark API 的常用功能與欄位。完整欄位規格可參考：

```text
YuantaSparkAPI_osx-arm64_Python/IO_Doc/
YuantaSparkAPI_osx-arm64_Python/YSendOrder.py
```

## Runtime

Mac/Linux 使用 Python 呼叫 .NET SDK：

```python
from pythonnet import load

load("coreclr")
```

本專案已改成使用專案內 `.dotnet/` runtime，入口是：

```bash
.venv/bin/python yuanta_smoke_test.py login
```

## Account Format

證券帳號格式：

```text
S + 分公司代號(4) + 帳號(7)
```

例如：

```text
S + 分公司代號4碼 + 帳號7碼
```

Mac/Linux 測試需填完整帳號格式，例如：

```text
YUANTA_ACCOUNT=Sxxxxxxxxxxx
```

## Environment

```text
UAT   測試環境
PROD  正式環境
```

目前正式環境登入、報價、庫存查詢已測通。

## Login

Mac/Linux 登入：

```python
api.Login(pfx_path, pfx_password, account, password)
```

欄位：

```text
PfxPath   PFX 憑證絕對路徑
PfxPass   PFX 憑證密碼
Account   登入帳號
Pass      登入密碼
```

回傳事件：

```text
LoginResult
LoginStatus.MsgCode
LoginStatus.MsgContent
LoginStatus.Count
LoginList
```

常見代碼：

```text
0001  執行成功
0000  執行失敗
0102  密碼凍結或未啟用
0112  無此權限使用功能
0016  請勿連續進行系統登入作業
```

## Quote Query

查完整報價：

```python
api.GetWatchListAll(account, quote_list)
```

輸入物件 `Quote`：

```text
MarketType   市場別，例如 enumMarketType.TWSE
StockCode    商品代號，例如 2885
```

常用回傳欄位 `QueryWatchList`：

```text
MarketNo
StkCode
StkName
YstPrice
OpenPrice
HighPrice
LowPrice
BuyPrice
SellPrice
DealPrice
TotalVol
UpStopPrice
DownStopPrice
Decimal
Time
```

本專案已測通：

```bash
.venv/bin/python yuanta_smoke_test.py quote
```

## Stock Inventory

股票庫存綜合總表：

```python
api.GetStoreSummary(account)
```

常用回傳欄位 `StkStore`：

```text
Account
TradeKind
MarketNo
MarketName
StkCode
StkName
StockQty
Price
Cost
TradingQty
MarketPrice
MarketAmt
ReturnAmt
BuyPrice
SellPrice
UpStopPrice
DownStopPrice
CurrencyType
OddTradingQty
```

本專案已測通：

```bash
.venv/bin/python yuanta_smoke_test.py summary
```

## Stock Order

國內現貨下單：

```python
api.SendStockOrder(account, stock_order_list)
```

輸入物件 `StockOrder`：

```text
Identify        識別碼
Account         下單帳號
APCode          市場別，0一般、2零股、4盤中零股、7盤後
TradeKind       00新單、03改量、04取消、07改價
OrderType       0現貨、3融資、4融券、5策略借券賣出、6避險借券賣出
StkCode         股票代號
BuySell         B買、S賣
PriceFlag       M市價、空白限價、H漲停、L跌停、-平盤
Price           委託價格，非限價填0
OrderQty        委託單位
OrderNo         委託書號，新單不用填
TradeDate       yyyy/MM/dd
BasketNo        自訂欄位，最多32個英數字
Time_in_force   0 ROD、3 IOC、4 FOK
```

回傳 `StkOrderData`：

```text
Identify
ReplyCode       0委託成功，其他失敗
OrderNO
TradeDate
ErrType
ErrNO
Advisory
```

本專案下單有雙重防呆：

```text
YUANTA_ENABLE_ORDER=YES
--confirm-send-order
```

預覽，不送單：

```bash
.venv/bin/python yuanta_smoke_test.py order-preview
```

真正送單：

```bash
.venv/bin/python yuanta_smoke_test.py send-stock-order --confirm-send-order
```

## Order And Trade Reports

委託成交綜合回報：

```python
api.GetOrderTradeReport(False, account)
```

回傳清單：

```text
StkOrderList       現貨委託
StkTradeList       現貨成交
FutOrderList       期貨委託
FutTradeList       期貨成交
OVStkOrderList     國外股票委託
OVStkTradeList     國外股票成交
OVFutOrderList     國外期貨委託
OVFutTradeList     國外期貨成交
```

現貨委託常用欄位：

```text
Account
TradeDate
MarketNo
CompanyNo
StkName
OrderType
BS
Price
PriceFlag
BeforeQty
AfterQty
OkQty
OrderStatus
AcceptDate
AcceptTime
OrderNo
ErrorNo
ErrorMessage
APCode
CancelFlag
ReduceFlag
BasketNo
```

## Real-Time Reports

即時回報查詢：

```python
api.GetRealReport(account)
api.GetRealReportMerge(account)
```

事件訂閱會透過 `OnResponse` 收到：

```text
RR_RealReport
RR_RealReportMerge
```

常用欄位：

```text
Account
RptType
OrderNo
MarketNo
CompanyNo
StkCName
OrderDate
OrderTime
OrderType
BS
Price
BeforeQty
OrderQty
OkQty
OrderStatus
OrderErrorNo
TradeCode
```

## Quote Subscription

指定欄位訂閱：

```python
api.SubscribeWatchlist(account, watchlist)
api.UnSubscribeWatchlist(account, watchlist)
```

完整報價訂閱：

```python
api.SubscribeWatchlistAll(account, watchlist_all)
api.UnSubscribeWatchlistAll(account, watchlist_all)
```

五檔：

```python
api.SubscribeFiveTickA(account, five_tick_list)
api.UnSubscribeFiveTickA(account, five_tick_list)
```

分時明細：

```python
api.SubscribeStockTick(account, stock_tick_list)
api.UnSubscribeStockTick(account, stock_tick_list)
```

## K Line

K 線查詢：

```python
api.GetKLine(account, kline_type, market_type, stk_code, start_date, end_date)
```

輸入：

```text
KLineType    K線週期
MarketType   市場別
StkCode      商品代號
SDate        yyyy/MM/dd
EDate        yyyy/MM/dd
```

回傳 `KLine`：

```text
TimeStamp
OpenPrice
HighPrice
LowPrice
ClosePrice
DealVol
```

查詢限制：

```text
1分K              單次1天，最大20天
5/15/30/60分K     單次5天，最大100天
日K               單次1年，最大10年
週K               單次5年，最大10年
月K               單次10年，最大10年
```

## Futures

國內期貨下單：

```python
api.SendFutureOrder(account, future_order_list)
```

國外期貨下單：

```python
api.SendOVFutureOrder(account, ov_future_order_list)
```

期貨庫存與權益：

```python
api.GetFutStoreSummary(account)
api.GetOVFutStoreSummary(account)
api.GetFutInterestStore(account, type, currency)
api.GetFutDepositOptimum(account)
api.GetFutSprStore(account)
api.SendFutureCombined(account, deposit_optimum_list)
api.SendFutureApart(account, fut_spr_store_list)
```

## Profit And Settlement

```python
api.GetUnrealizedGainLossDetail(account, market_type, stk_code)
api.GetHisRealizedGainLoss(account, start_date, end_date)
api.GetStkHistoryReportReversal(account, realized_gain_loss)
api.GetStkTransactionOutlay(account)
api.GetBankBalance(account)
```

## Condition Orders

條件/策略單：

```python
api.SendAlgoCOOdrStrategy(account, strategy_list)
api.GetConditionStrategy(account, strategy_type, stk_code)
api.GetHisConditionStrategy(account, strategy_type, stk_code, start_date, end_date)
api.DeleteAlgoCOOdrStrategy(account, delete_strategy_list)
```

策略類型包含：

```text
STO                 停損利
MLP                 移動鎖利
OCO                 二擇一
SpiderStrategy      多條件/蜘蛛單
MS_SpiderStrategy   母子單
MS_DayTradeSpiderStrategy
```

## Current Tested Commands

登入：

```bash
.venv/bin/python yuanta_smoke_test.py login
```

報價：

```bash
.venv/bin/python yuanta_smoke_test.py quote
```

庫存：

```bash
.venv/bin/python yuanta_smoke_test.py summary
```

日 K：

```bash
.venv/bin/python yuanta_smoke_test.py kline
```

預覽下單：

```bash
.venv/bin/python yuanta_smoke_test.py order-preview
```
