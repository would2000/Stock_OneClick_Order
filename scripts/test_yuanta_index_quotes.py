#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.yuanta.client import YuantaClientError, get_yuanta_client


@dataclass(frozen=True)
class Candidate:
    market: str
    symbol: str


CANDIDATES = [
    Candidate("TWSE", "TSE.TW"),
    Candidate("TWSE", "TAIEX"),
    Candidate("TWSE", "IX0001"),
    Candidate("TWSE", "0000"),
    Candidate("TWSE", "000001"),
    Candidate("TWSE", "Y9999"),
    Candidate("TWOTC", "OTC.TW"),
    Candidate("TWOTC", "OTC"),
    Candidate("TWOTC", "IX0043"),
    Candidate("TWOTC", "0000"),
    Candidate("TWOTC", "000001"),
    Candidate("TWOTC", "Y9999"),
]


def format_value(value: object) -> str:
    if value is None:
        return "-"
    return str(value)


def main() -> int:
    client = get_yuanta_client()
    try:
        status = client.connect()
        print(f"connect: {status.state} account_name={status.account_name or '-'}")
        print("market,symbol,status,name,deal,open,high,low,total_volume,up_limit,down_limit,error")
        for candidate in CANDIDATES:
            try:
                rows = client.get_quotes([candidate.symbol], candidate.market)
                if not rows:
                    print(f"{candidate.market},{candidate.symbol},NO_ROWS,,,,,,,,,")
                    continue
                quote = rows[0]
                ok = quote.deal_price is not None and quote.deal_price > 0
                print(
                    ",".join(
                        [
                            candidate.market,
                            candidate.symbol,
                            "OK" if ok else "EMPTY_PRICE",
                            quote.name,
                            format_value(quote.deal_price),
                            format_value(quote.open_price),
                            format_value(quote.high_price),
                            format_value(quote.low_price),
                            format_value(quote.total_volume),
                            format_value(quote.up_limit),
                            format_value(quote.down_limit),
                            "",
                        ]
                    )
                )
            except Exception as exc:  # noqa: BLE001 - smoke script should continue every candidate
                print(f"{candidate.market},{candidate.symbol},ERROR,,,,,,,,,{str(exc).replace(',', ';')}")
    except YuantaClientError as exc:
        print(f"connect error: {exc}")
        return 1
    finally:
        client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
