import asyncio
import glob
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.quote_stream import stream_router
from .api.routes import router
from .config import get_settings
from .database import init_db
from .market_data.index_sampler import run_index_sampler
from .trading.mit import clear_stale_mit_orders, run_mit_engine
from .yuanta.client import get_yuanta_client


def _restrict_log_perms() -> None:
    """收緊 log 檔權限為 0600：log（含帳號/IP 等明文）不應被同機其他使用者或備份讀取。"""
    root = get_settings().project_root
    for path in [*glob.glob(str(root / "logs" / "*.log")), str(root / "shioaji.log")]:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


# 本機自用程式：關閉 /docs、/redoc、/openapi.json，不對外暴露端點地圖（縮小攻擊面）。
app = FastAPI(title="Yuanta AutoTrading API", docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    init_db()
    _restrict_log_perms()  # 收緊 log 權限為 0600
    clear_stale_mit_orders()  # 啟動時換日清空非今日 MIT
    app.state.mit_engine_task = asyncio.create_task(run_mit_engine())
    app.state.index_sampler_task = asyncio.create_task(run_index_sampler())


@app.on_event("shutdown")
async def shutdown() -> None:
    for name in ("mit_engine_task", "index_sampler_task"):
        task = getattr(app.state, name, None)
        if task:
            task.cancel()
    get_yuanta_client().disconnect()
    try:
        from .brokers.shioaji_client import _client as shioaji_client
        if shioaji_client is not None:
            shioaji_client.disconnect()
    except Exception:
        pass


app.include_router(router)
app.include_router(stream_router)
