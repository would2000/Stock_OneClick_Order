import argparse
from datetime import datetime
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import threading
import time
from typing import Any


def resolve_sdk_dir(root: pathlib.Path) -> pathlib.Path:
    """選出元大 SDK 資料夾：環境變數 YUANTA_SDK_DIR > 平台慣用名 > 自動探索。

    （與 backend/app/yuanta/client.py 內的同名函式保持一致。）
    """
    override = os.environ.get("YUANTA_SDK_DIR", "").strip()
    if override:
        path = pathlib.Path(override).expanduser()
        return path if path.is_absolute() else root / path

    machine = platform.machine().lower()
    system = platform.system()
    if system == "Darwin":
        preferred = (
            "YuantaSparkAPI_osx-arm64_Python"
            if machine in ("arm64", "aarch64")
            else "YuantaSparkAPI_osx-x64_Python"
        )
    elif system == "Windows":
        preferred = "YuantaSparkAPI_win-x64_Python"
    elif system == "Linux":
        preferred = "YuantaSparkAPI_linux-x64_Python"
    else:
        preferred = "YuantaSparkAPI_osx-arm64_Python"

    if (root / preferred).is_dir():
        return root / preferred
    for candidate in sorted(root.glob("YuantaSparkAPI_*_Python")):
        if candidate.is_dir():
            return candidate
    return root / preferred


ROOT = pathlib.Path(__file__).resolve().parent
SDK_DIR = resolve_sdk_dir(ROOT)
DOTNET_ROOT = ROOT / ".dotnet"
PYTHONNET_RUNTIME_CONFIG = ROOT / "pythonnet.runtimeconfig.json"


def load_env(path: pathlib.Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}. Copy .env.example to .env and fill it in.")
    return value


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer.") from exc


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a number.") from exc


def bootstrap_dotnet() -> None:
    try:
        from pythonnet import load
    except ModuleNotFoundError as exc:
        raise SystemExit("Missing pythonnet. Run: python -m pip install -r requirements.txt") from exc

    if not SDK_DIR.exists():
        raise SystemExit(f"SDK folder not found: {SDK_DIR}")
    if not DOTNET_ROOT.exists():
        raise SystemExit("Missing .dotnet runtime. See README.md installation steps.")

    sys.path.append(str(SDK_DIR))
    os.environ.setdefault("PYTHONNET_RUNTIME", "coreclr")
    os.environ.setdefault("DOTNET_ROOT", str(DOTNET_ROOT))
    os.environ["PATH"] = f"{DOTNET_ROOT}{os.pathsep}{os.environ.get('PATH', '')}"
    load("coreclr", runtime_config=str(PYTHONNET_RUNTIME_CONFIG), dotnet_root=str(DOTNET_ROOT))

    import clr  # noqa: PLC0415

    clr.AddReference("System.Collections")
    clr.AddReference("YuantaSparkAPI")


def status_text(status: Any) -> str:
    code = getattr(status, "MsgCode", "")
    content = getattr(status, "MsgContent", "")
    count = getattr(status, "Count", "")
    return f"{code} {content} count={count}".strip()


def market_type(name: str):
    from YuantaOneAPI import enumMarketType  # noqa: PLC0415

    value = name.strip().upper()
    if not value:
        value = "TWSE"
    return getattr(enumMarketType, value)


def environment_mode(name: str):
    from YuantaOneAPI import enumEnvironmentMode  # noqa: PLC0415

    value = name.strip().upper()
    if value == "PROD":
        return enumEnvironmentMode.PROD
    if value == "UAT":
        return enumEnvironmentMode.UAT
    raise SystemExit("YUANTA_ENV must be UAT or PROD.")


def kline_type(value: str):
    from YuantaOneAPI import KLineType  # noqa: PLC0415

    aliases = {
        "1M": 0,
        "5M": 1,
        "15M": 2,
        "30M": 3,
        "60M": 4,
        "DAY": 11,
        "D": 11,
        "DAILY": 11,
        "WEEK": 12,
        "W": 12,
        "MONTH": 13,
        "M": 13,
    }
    raw = value.strip().upper()
    if raw in aliases:
        return KLineType(aliases[raw])
    try:
        return KLineType(int(raw))
    except ValueError as exc:
        raise SystemExit("YUANTA_KLINE_TYPE must be a number or one of DAY/WEEK/MONTH/1M/5M/15M/30M/60M.") from exc


def warn_account_shape(account: str) -> None:
    normalized = account.strip()
    if normalized.startswith("Q"):
        print("Warning: YUANTA_ACCOUNT starts with Q. Yuanta examples use trading accounts like S + account number, not personal ID.")
    if "-" in normalized:
        print("Warning: YUANTA_ACCOUNT contains '-'. Yuanta examples use a compact account string without dashes.")


def order_config() -> dict[str, Any]:
    side = os.environ.get("YUANTA_ORDER_SIDE", "B").strip().upper()
    if side not in {"B", "S"}:
        raise SystemExit("YUANTA_ORDER_SIDE must be B or S.")

    qty = env_int("YUANTA_ORDER_QTY", 1)
    if qty <= 0:
        raise SystemExit("YUANTA_ORDER_QTY must be greater than 0.")

    price = env_float("YUANTA_ORDER_PRICE", 35.0)
    if price < 0:
        raise SystemExit("YUANTA_ORDER_PRICE must be greater than or equal to 0.")

    return {
        "symbol": os.environ.get("YUANTA_ORDER_SYMBOL", "2885").strip(),
        "side": side,
        "price": price,
        "qty": qty,
        "price_flag": os.environ.get("YUANTA_ORDER_PRICE_FLAG", "M").strip(),
        "order_type": os.environ.get("YUANTA_ORDER_TYPE", "0").strip(),
        "trade_kind": env_int("YUANTA_ORDER_TRADE_KIND", 0),
        "ap_code": env_int("YUANTA_ORDER_AP_CODE", 0),
        "time_in_force": os.environ.get("YUANTA_ORDER_TIME_IN_FORCE", "0").strip(),
    }


def check_certificate_password(cert_path: pathlib.Path, cert_password: str) -> None:
    openssl = shutil.which("openssl")
    if not openssl:
        return

    result = subprocess.run(
        [openssl, "pkcs12", "-in", str(cert_path), "-nokeys", "-noout", "-passin", "stdin"],
        input=f"{cert_password}\n",
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip().splitlines()[0] if result.stderr.strip() else "invalid password"
        raise SystemExit(f"Certificate password check failed: {message}")


def print_order_preview(account: str, config: dict[str, Any]) -> None:
    side_text = "BUY" if config["side"] == "B" else "SELL"
    print("Stock order preview")
    print(f"account={account}")
    print(f"symbol={config['symbol']}")
    print(f"side={config['side']} ({side_text})")
    print(f"price={config['price']}")
    print(f"qty={config['qty']}")
    print(f"price_flag={config['price_flag']}")
    print(f"order_type={config['order_type']}")
    print(f"trade_kind={config['trade_kind']}")
    print(f"ap_code={config['ap_code']}")
    print(f"time_in_force={config['time_in_force']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Yuanta Spark API smoke test")
    parser.add_argument(
        "action",
        choices=["login", "quote", "summary", "kline", "order-preview", "send-stock-order"],
        help="login, query quote, query stock inventory, query K line, preview an order, or send a stock order",
    )
    parser.add_argument("--wait", type=float, default=8.0, help="seconds to wait for async responses")
    parser.add_argument("--open-wait", type=float, default=5.0, help="seconds to wait after Open before Login")
    parser.add_argument(
        "--confirm-send-order",
        action="store_true",
        help="required for send-stock-order in addition to YUANTA_ENABLE_ORDER=YES",
    )
    args = parser.parse_args()

    load_env(ROOT / ".env")
    account = require_env("YUANTA_ACCOUNT")
    password = require_env("YUANTA_PASSWORD")
    cert_path = pathlib.Path(require_env("YUANTA_CERT_PATH")).expanduser().resolve()
    cert_password = require_env("YUANTA_CERT_PASSWORD")
    env_name = os.environ.get("YUANTA_ENV", "UAT")
    symbol = os.environ.get("YUANTA_SYMBOL", "2885")
    market_name = os.environ.get("YUANTA_MARKET", "TWSE")
    kline_start = os.environ.get("YUANTA_KLINE_START", "2025/01/01")
    kline_end = os.environ.get("YUANTA_KLINE_END", "2025/03/26")
    kline_type_name = os.environ.get("YUANTA_KLINE_TYPE", "11")
    stock_order = order_config()
    warn_account_shape(account)

    if args.action == "order-preview":
        print_order_preview(account, stock_order)
        return 0

    if args.action == "send-stock-order":
        if os.environ.get("YUANTA_ENABLE_ORDER", "").strip().upper() != "YES":
            print("Refusing to send order because YUANTA_ENABLE_ORDER is not YES.")
            print_order_preview(account, stock_order)
            return 4
        if not args.confirm_send_order:
            print("Refusing to send order without --confirm-send-order.")
            print_order_preview(account, stock_order)
            return 5

    if not cert_path.exists():
        raise SystemExit(f"Certificate not found: {cert_path}")
    check_certificate_password(cert_path, cert_password)

    bootstrap_dotnet()

    from System.Collections.Generic import List  # noqa: PLC0415
    from YuantaOneAPI import (  # noqa: PLC0415
        OnResponseEventHandler,
        Quote,
        StockOrder,
        YuantaSparkAPITrader,
        enumLogType,
    )

    ready = threading.Event()
    got_response = threading.Event()
    login_status = {"ok": False}

    def on_response(int_mark, dw_index, str_index, obj_handle, obj_value):
        got_response.set()
        print("\n## response")
        print(f"mark={int_mark} index={str_index}")

        if str_index == "Login":
            status = obj_value.LoginStatus
            print(status_text(status))
            for item in obj_value.LoginList:
                print(f"account={item.Account} name={item.Name} investor_id={item.InvestorID}")
            login_status["ok"] = getattr(status, "Count", 0) > 0
            ready.set()
            return

        if str_index == "SendStockOrder":
            result_count = obj_value.ResultCount
            print(status_text(result_count))
            for item in obj_value.ResultList:
                trade_date = item.TradeDate
                date_text = f"{trade_date.Year}/{trade_date.Month}/{trade_date.Day}"
                print(
                    f"identify={item.Identify} reply={item.ReplyCode} "
                    f"order_no={item.OrderNO} trade_date={date_text} "
                    f"err_type={item.ErrType} err_no={item.ErrNO} advisory={item.Advisory}"
                )
            return

        if str_index == "GetWatchListAll":
            for item in obj_value.QueryWatchList:
                print(
                    f"{item.MarketNo} {item.StkCode} {item.StkName} "
                    f"deal={item.DealPrice} bid={item.BuyPrice} ask={item.SellPrice}"
                )
            return

        if str_index == "GetStoreSummary":
            print(f"stock stores={obj_value.StkStoreList.Count}")
            for item in obj_value.StkStoreList:
                print(f"{item.Account} {item.StkCode} {item.StkName} qty={item.StockQty} market_amt={item.MarketAmt}")
            return

        if str_index == "GetKLine":
            print(f"market={obj_value.MarketNo} stock={obj_value.StockCode} rows={obj_value.KLineList.Count}")
            for item in obj_value.KLineList:
                ts = item.TimeStamp
                timestamp = f"{ts.Year:04d}-{ts.Month:02d}-{ts.Day:02d} {ts.Hour:02d}:{ts.Minute:02d}:{ts.Second:02d}"
                print(
                    f"{timestamp} "
                    f"open={item.OpenPrice} high={item.HighPrice} low={item.LowPrice} "
                    f"close={item.ClosePrice} vol={item.DealVol}"
                )
            return

        print(obj_value)

    api = YuantaSparkAPITrader(str(ROOT / "logs"))
    api.OnResponse += OnResponseEventHandler(on_response)
    api.SetLogType(enumLogType.COMMON)

    try:
        print(f"Opening Yuanta API: {env_name}")
        open_ok = api.Open(environment_mode(env_name))
        print(f"Open call returned: {open_ok}")
        time.sleep(args.open_wait)

        print(f"Logging in account: {account}")
        ok = api.Login(str(cert_path), cert_password, account, password)
        print(f"Login call returned: {ok}")
        if ok is False:
            print("Login was rejected before an async response was emitted. Check YUANTA_ACCOUNT format, YUANTA_ENV, and password.")

        if not ready.wait(args.wait):
            print("Login response was not received before timeout.")
            return 2
        if not login_status["ok"]:
            print("Login did not return any available account. Stop here.")
            return 3

        if args.action == "quote":
            quote = Quote()
            quote.MarketType = market_type(market_name)
            quote.StockCode = symbol
            quotes = List[Quote]()
            quotes.Add(quote)
            got_response.clear()
            api.GetWatchListAll(account, quotes)
            got_response.wait(args.wait)

        if args.action == "summary":
            got_response.clear()
            api.GetStoreSummary(account)
            got_response.wait(args.wait)

        if args.action == "kline":
            got_response.clear()
            api.GetKLine(account, kline_type(kline_type_name), market_type(market_name), symbol, kline_start, kline_end)
            got_response.wait(args.wait)

        if args.action == "send-stock-order":
            print_order_preview(account, stock_order)
            order = StockOrder()
            order.Identify = 1
            order.Account = account
            order.APCode = stock_order["ap_code"]
            order.TradeKind = stock_order["trade_kind"]
            order.OrderType = stock_order["order_type"]
            order.StkCode = stock_order["symbol"]
            order.PriceFlag = stock_order["price_flag"]
            order.Price = stock_order["price"]
            order.OrderQty = stock_order["qty"]
            order.BuySell = stock_order["side"]
            order.OrderNo = ""
            order.TradeDate = datetime.today().strftime("%Y/%m/%d")
            order.BasketNo = ""
            order.Time_in_force = stock_order["time_in_force"]

            orders = List[StockOrder]()
            orders.Add(order)
            got_response.clear()
            ok = api.SendStockOrder(account, orders)
            print(f"SendStockOrder call returned: {ok}")
            got_response.wait(args.wait)

        return 0
    finally:
        try:
            api.LogOut()
        except Exception:
            pass
        api.Close()
        api.Dispose()


if __name__ == "__main__":
    raise SystemExit(main())
