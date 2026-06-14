"""登入工作階段：依登入畫面選的環境設定憑證/金鑰、切換券商並連線。

- sim：純本機沙盒，免任何安控與憑證，登入即可隨意下單。
- yuanta / sinopac：實單環境，套用登入畫面填的帳號/憑證/金鑰（留白沿用 .env），
  連線成功後開啟下單總開關（仍保有送單前確認等實單保護）。
"""

from pathlib import Path

from .broker import BROKER_LABELS, get_active_client, is_sim_session, set_active_broker
from .config import get_settings
from .trading.schemas import LoginRequest, LoginState
from .yuanta.client import YuantaClientError, get_yuanta_client


def _validate_cert_path(cert_path: str) -> str:
    """登入請求帶的憑證路徑只允許落在受控上傳目錄（data/runtime_certs）內，
    防止用任意絕對路徑讓 openssl/SDK 探測本機檔案（資訊預言機）。留白則沿用 .env 設定。"""
    if not cert_path:
        return ""
    allowed_root = (get_settings().data_dir / "runtime_certs").resolve()
    resolved = Path(cert_path).resolve()
    if resolved == allowed_root or allowed_root in resolved.parents:
        return str(resolved)
    raise YuantaClientError("憑證路徑不在允許範圍，請改用「憑證上傳」功能選擇憑證。")

_state: LoginState = LoginState(logged_in=False)


# 券商 SDK 的英文登入錯誤 → 中文（元大與永豐共用，依序比對，取第一個命中）。
_ERROR_RULES: list[tuple[str, str]] = [
    ("api_key must be at least", "API Key 長度不足，請確認是否完整貼上正確的 API Key。"),
    ("secret_key must be at least", "Secret Key 長度不足，請確認是否完整貼上正確的 Secret Key。"),
    ("api_key", "API Key 不正確或格式有誤，請確認後重試。"),
    ("secret_key", "Secret Key 不正確或格式有誤，請確認後重試。"),
    ("person_id", "身分證字號格式有誤，請確認後重試。"),
    ("activate_ca", "CA 憑證啟用失敗，請確認憑證檔與憑證密碼。"),
    ("ca_passwd", "CA 憑證密碼錯誤，請確認後重試。"),
    ("ca path", "找不到憑證檔，請確認憑證路徑。"),
    (".pfx", "憑證檔載入失敗，請確認憑證檔與憑證密碼。"),
    ("certificate", "憑證錯誤，請確認憑證檔與憑證密碼。"),
    ("unauthorized", "帳號或金鑰未授權，請確認 API 下單權限是否開通。"),
    ("permission", "權限不足，請確認 API 下單權限是否開通。"),
    ("login validation error", "登入驗證失敗：帳號或金鑰格式不正確。"),
    ("invalid", "帳號或金鑰不正確，請確認後重試。"),
    ("timeout", "連線逾時，請檢查網路後再試。"),
    ("timed out", "連線逾時，請檢查網路後再試。"),
    ("connection", "網路連線失敗，請檢查網路後再試。"),
    ("password", "密碼錯誤，請確認後重試。"),
    ("account", "帳號錯誤，請確認後重試。"),
    ("sdk folder not found", "找不到元大交易元件（SDK），請依 README 向元大下載對應平台的 SDK 放到專案資料夾後再試。"),
    ("missing .dotnet", "缺少 .NET 執行環境，請依 README 安裝後再試。"),
    ("yuanta_env must be", "環境設定錯誤（YUANTA_ENV 必須為 UAT 或 PROD）。"),
    ("missing shioaji_api_key", "尚未設定永豐 API Key / Secret Key。"),
    ("missing .env", "尚未設定帳號/憑證，請於登入畫面填寫或於 .env 設定。"),
]


def translate_broker_error(raw: str) -> str:
    """把券商 SDK 的英文錯誤轉成中文，並保留原始英文訊息供除錯。"""
    text = (raw or "").strip()
    if not text:
        return "登入失敗。"
    low = text.lower()
    for needle, zh in _ERROR_RULES:
        if needle in low:
            return f"{zh}（原始訊息：{text}）"
    return f"登入失敗：{text}"


def get_login_state() -> LoginState:
    # 後端可能已連線但前端剛重新整理：以實際連線狀態校正。
    if _state.logged_in:
        try:
            if not get_active_client().status().connected:
                _state.logged_in = False
        except Exception:
            _state.logged_in = False
    return _state


# 登入畫面各欄位 → Settings 屬性（依券商）。憑證路徑不在記住範圍（沿用 .env）。
_REMEMBER_MAP: dict[str, dict[str, str]] = {
    "yuanta": {
        "account": "yuanta_account",
        "password": "yuanta_password",
        "cert_password": "yuanta_cert_password",
    },
    "sinopac": {
        "api_key": "shioaji_api_key",
        "secret_key": "shioaji_secret_key",
        "person_id": "shioaji_person_id",
        "cert_password": "shioaji_ca_password",
    },
}


def _credentials_path():
    return get_settings().data_dir / "credentials.json"


def _load_credentials() -> dict[str, str]:
    import json  # noqa: PLC0415

    try:
        data = json.loads(_credentials_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_credentials(data: dict[str, str]) -> None:
    import json  # noqa: PLC0415

    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def remembered_fields() -> list[str]:
    """目前已記住的 Settings 屬性名（不含值），給登入畫面預先勾選。"""
    return sorted(_load_credentials().keys())


def _apply_credentials(broker: str, req: LoginRequest, settings) -> None:
    """套用登入欄位：表單值 > 已記住值 > .env；並依各欄 remember 旗標更新受限儲存。"""
    stored = _load_credentials()
    remember = req.remember or {}
    payload_values = {
        "account": req.account,
        "password": req.password,
        "cert_password": req.cert_password,
        "api_key": req.api_key,
        "secret_key": req.secret_key,
        "person_id": req.person_id,
    }
    for field, attr in _REMEMBER_MAP[broker].items():
        value = (payload_values.get(field) or "").strip()
        want = bool(remember.get(field))
        if value:
            setattr(settings, attr, value)
        elif stored.get(attr):
            setattr(settings, attr, stored[attr])  # 留白沿用已記住值
        effective = value or stored.get(attr) or ""
        if want and effective:
            stored[attr] = effective
        elif not want:
            stored.pop(attr, None)  # 取消勾選＝忘記
    _save_credentials(stored)


def _apply_fugle_key(req: LoginRequest, settings) -> None:
    """套用登入畫面填入的富果金鑰：填了就存進受限儲存並記住，留白沿用已儲存值。

    模擬沙盒用它把合成報價升級為真實行情；金鑰有變動時重置 Fugle 連線以套用新值。
    """
    stored = _load_credentials()
    value = (req.fugle_api_key or "").strip()
    if value and value != stored.get("fugle_api_key"):
        stored["fugle_api_key"] = value
        _save_credentials(stored)
    effective = value or stored.get("fugle_api_key") or settings.fugle_api_key
    if effective != settings.fugle_api_key:
        settings.fugle_api_key = effective
        from .brokers.fugle_client import reset_fugle  # noqa: PLC0415

        reset_fugle()


def _reset_runtime_flags() -> None:
    """把實單相關旗標還原為非實單安全預設，避免上一次實單登入殘留到 sim / 登出後
    （否則 yuanta_enable_order 會永久 True、health 一直回報實單）。"""
    settings = get_settings()
    settings.yuanta_enable_order = False
    settings.yuanta_env = "UAT"
    settings.shioaji_simulation = True


def _clear_runtime_certs() -> None:
    """清除登入時上傳的暫存憑證私鑰，避免登出/換帳號後私鑰殘留磁碟。"""
    import shutil  # noqa: PLC0415

    cert_dir = get_settings().data_dir / "runtime_certs"
    try:
        if cert_dir.exists():
            shutil.rmtree(cert_dir, ignore_errors=True)
    except OSError:
        pass


def _disconnect_all() -> None:
    try:
        get_yuanta_client().disconnect()
    except Exception:
        pass
    try:
        from .brokers.shioaji_client import _client as shioaji_client  # noqa: PLC0415

        if shioaji_client is not None:
            shioaji_client.disconnect()
    except Exception:
        pass


def login(req: LoginRequest) -> LoginState:
    global _state
    settings = get_settings()
    _disconnect_all()
    # 每次登入前先還原為非實單安全預設，再依環境設定，避免旗標殘留。
    _reset_runtime_flags()
    # 富果金鑰（選填，各環境通用）：讓模擬沙盒也能用真實行情。
    _apply_fugle_key(req, settings)
    # 憑證路徑白名單檢查（不合法直接擋下登入）。
    cert_path = _validate_cert_path(req.cert_path)

    if req.environment == "sim":
        # 沙盒改為持久化模擬帳戶：登入時不再清空，委託/成交/部位保留在 trading.db。
        set_active_broker("sim")
        status = get_active_client().connect()
    elif req.environment == "yuanta":
        _apply_credentials("yuanta", req, settings)
        if cert_path:
            settings.yuanta_cert_path = cert_path
        settings.yuanta_env = "PROD"
        settings.yuanta_enable_order = True
        set_active_broker("yuanta")
        status = get_active_client().connect()
    elif req.environment == "sinopac":
        _apply_credentials("sinopac", req, settings)
        if cert_path:
            settings.shioaji_ca_path = cert_path
        settings.shioaji_simulation = False
        settings.yuanta_enable_order = True  # 兩家共用的實單總開關
        set_active_broker("sinopac")
        status = get_active_client().connect()
    else:
        raise YuantaClientError("未知的登入環境。")

    _state = LoginState(
        logged_in=status.connected,
        environment=req.environment,
        broker=req.environment,
        broker_label=BROKER_LABELS.get(req.environment, req.environment),
        account=status.account,
        account_name=status.account_name,
        is_sim=is_sim_session(),
        message="" if status.connected else (status.last_error or "連線失敗。"),
    )
    return _state


def logout() -> LoginState:
    global _state
    _disconnect_all()
    _reset_runtime_flags()
    _clear_runtime_certs()
    _state = LoginState(logged_in=False, message="已登出。")
    return _state
