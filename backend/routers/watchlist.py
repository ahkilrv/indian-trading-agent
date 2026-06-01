"""Watchlist CRUD endpoints."""

from fastapi import APIRouter
from backend.models import WatchlistItem
from backend.db import get_watchlist, add_to_watchlist, remove_from_watchlist
from tradingagents.utils.ticker import normalize_ticker
import yfinance as yf

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _stock_source() -> str:
    try:
        from tradingagents.dataflows.interface import get_data_source_label
        return get_data_source_label("get_stock_data")
    except Exception:
        return "Yahoo Finance"


@router.get("")
def list_watchlist():
    """Get all watchlist items with current prices."""
    items = get_watchlist()
    enriched = []
    for item in items:
        ticker = item["ticker"]
        try:
            symbol = normalize_ticker(ticker)
            t = yf.Ticker(symbol)
            hist = t.history(period="2d")
            if not hist.empty:
                current = hist.iloc[-1]
                prev = hist.iloc[-2]["Close"] if len(hist) > 1 else current["Close"]
                price = current["Close"]
                change = price - prev
                enriched.append({
                    **item,
                    "symbol": symbol,
                    "price": round(price, 2),
                    "change": round(change, 2),
                    "change_percent": round(change / prev * 100, 2) if prev else 0,
                })
            else:
                enriched.append({**item, "symbol": symbol, "price": None, "change": None, "change_percent": None})
        except Exception:
            enriched.append({**item, "symbol": ticker, "price": None, "change": None, "change_percent": None})

    source = _stock_source()
    for e in enriched:
        e["data_source"] = source
    return enriched


@router.post("")
def add_watchlist_item(item: WatchlistItem):
    """Add a ticker to the watchlist."""
    symbol = normalize_ticker(item.ticker)
    # Get company name
    name = item.name
    if not name:
        try:
            t = yf.Ticker(symbol)
            name = t.info.get("shortName", item.ticker.upper())
        except Exception:
            name = item.ticker.upper()

    add_to_watchlist(item.ticker.upper(), item.exchange, name)
    return {"status": "added", "ticker": item.ticker.upper(), "name": name}


@router.delete("/{ticker}")
def delete_watchlist_item(ticker: str):
    """Remove a ticker from the watchlist."""
    remove_from_watchlist(ticker)
    return {"status": "removed", "ticker": ticker}
