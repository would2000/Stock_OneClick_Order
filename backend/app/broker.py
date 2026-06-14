"""Active-broker registry: routes/streams call get_active_client() and the
user switches between Yuanta and SinoPac (Shioaji) at runtime."""

from .config import get_settings
from .yuanta.client import get_yuanta_client

AVAILABLE_BROKERS = ("yuanta", "sinopac")
BROKER_LABELS = {"yuanta": "元大證券", "sinopac": "永豐金證券", "sim": "模擬環境"}
# 包含登入時的模擬環境（沙盒），不在使用者可切換清單內。
SELECTABLE_BROKERS = ("sim", "yuanta", "sinopac")

_active: str | None = None


def get_active_broker() -> str:
    global _active
    if _active is None:
        configured = get_settings().default_broker
        _active = configured if configured in AVAILABLE_BROKERS else "yuanta"
    return _active


def set_active_broker(name: str) -> str:
    global _active
    if name not in SELECTABLE_BROKERS:
        raise ValueError(f"Unknown broker: {name}")
    _active = name
    return _active


def is_sim_session() -> bool:
    return get_active_broker() == "sim"


def get_active_client():
    active = get_active_broker()
    if active == "sim":
        from .brokers.mock_client import get_mock_client  # noqa: PLC0415

        return get_mock_client()
    if active == "sinopac":
        from .brokers.shioaji_client import get_shioaji_client  # noqa: PLC0415

        return get_shioaji_client()
    return get_yuanta_client()
