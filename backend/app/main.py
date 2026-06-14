import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.quote_stream import stream_router
from .api.routes import router
from .database import init_db
from .market_data.index_sampler import run_index_sampler
from .trading.mit import run_mit_engine
from .yuanta.client import get_yuanta_client


app = FastAPI(title="Yuanta AutoTrading API")

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
