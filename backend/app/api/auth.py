"""敏感端點的 API 金鑰驗證。

威脅模型：後端綁定 127.0.0.1，主要防的是「同機其他程序」與「惡意網頁的
CSRF」。要求自訂標頭 X-API-Key 會強制瀏覽器走 CORS preflight，因此跨來源的
簡單請求無法偽造下單；同機程序則須先取得金鑰才能呼叫交易端點。

未設定 API_KEY 時一律拒絕（fail closed），避免誤以為端點已受保護。
"""

import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from ..config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(provided: str | None = Security(_api_key_header)) -> None:
    expected = get_settings().api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="伺服器未設定 API_KEY，敏感端點已停用。請於 .env 設定 API_KEY。",
        )
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key 無效或缺少。",
        )
