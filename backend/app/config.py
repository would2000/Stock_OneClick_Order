from functools import lru_cache
from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Settings:
    def __init__(self) -> None:
        load_env(PROJECT_ROOT / ".env")
        self.project_root = PROJECT_ROOT
        self.backend_root = BACKEND_ROOT
        self.data_dir = PROJECT_ROOT / "data"
        self.database_path = Path(os.getenv("TRADING_DB_PATH", self.data_dir / "trading.db"))
        self.market_data_root = os.getenv(
            "TW_MARKET_DATA_ROOT",
            "/path/to/local/Library/CloudStorage/GoogleDrive-example-account/我的雲端硬碟/vault/專案庫/TW_Market_Data_Backfill",
        )
        self.yuanta_account = os.getenv("YUANTA_ACCOUNT", "")
        self.yuanta_password = os.getenv("YUANTA_PASSWORD", "")
        self.yuanta_cert_path = os.getenv("YUANTA_CERT_PATH", "")
        self.yuanta_cert_password = os.getenv("YUANTA_CERT_PASSWORD", "")
        self.yuanta_env = os.getenv("YUANTA_ENV", "UAT")
        self.yuanta_enable_order = os.getenv("YUANTA_ENABLE_ORDER", "NO").upper() == "YES"
        self.default_market = os.getenv("YUANTA_MARKET", "TWSE")
        self.default_symbol = os.getenv("YUANTA_SYMBOL", "2885")
        # SinoPac (永豐金) Shioaji credentials
        self.shioaji_api_key = os.getenv("SHIOAJI_API_KEY", "")
        self.shioaji_secret_key = os.getenv("SHIOAJI_SECRET_KEY", "")
        self.shioaji_ca_path = os.getenv("SHIOAJI_CA_PATH", "")
        self.shioaji_ca_password = os.getenv("SHIOAJI_CA_PASSWORD", "")
        self.shioaji_person_id = os.getenv("SHIOAJI_PERSON_ID", "")
        self.shioaji_simulation = os.getenv("SHIOAJI_SIMULATION", "YES").upper() == "YES"
        self.default_broker = os.getenv("BROKER", "yuanta").lower()
        # 本機 API 存取金鑰：保護下單/連線/風控等敏感端點。未設定時敏感端點一律拒絕（fail closed）。
        self.api_key = os.getenv("API_KEY", "")
        # 富果 Fugle MarketData 報價（模擬環境使用真實行情）。
        self.fugle_api_key = os.getenv("FUGLE_API_KEY", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
