from __future__ import annotations

from pathlib import Path

from ..config import get_settings
from ..trading.schemas import Candidate


def get_today_candidates() -> list[Candidate]:
    settings = get_settings()
    root = Path(settings.market_data_root)

    if not root.exists():
        return [
            Candidate(
                symbol="2885",
                name="元大金",
                strategy_tag="manual_seed",
                score=0.5,
                reason="TW_MARKET_DATA_ROOT is not available on this machine; using a safe manual seed.",
                risk_level="medium",
            )
        ]

    return [
        Candidate(
            symbol="2885",
            name="元大金",
            strategy_tag="watchlist_seed",
            score=0.55,
            reason="Market data project folder is present. Replace this seed with feature-based screening next.",
            risk_level="medium",
        ),
        Candidate(
            symbol="2330",
            name="台積電",
            strategy_tag="watchlist_seed",
            score=0.52,
            reason="Large-cap liquidity seed for quote and UI validation.",
            risk_level="low",
        ),
    ]
