"""NSE-specific data functions via nsepython library.

Provides OHLCV history, technical indicators (via stockstats), and live quotes
by querying NSE's public API endpoints through nsepython.

IMPORTANT: NSE now uses Akamai bot detection. Access may be blocked from
non-Indian IPs or during market hours. The vendor routing layer in
interface.py automatically falls back to yfinance on failure.

Date format: all public functions accept yyyy-mm-dd (ISO). Internally
converted to dd-mm-yyyy for the nsepython library.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── Ticker helpers ──────────────────────────────────────────────────


def _to_nse_symbol(ticker: str) -> str:
    """Strip exchange suffixes so nsepython receives bare NSE symbols.

    RELIANCE.NS  →  RELIANCE
    RELIANCE.BO  →  RELIANCE
    RELIANCE     →  RELIANCE
    """
    for suffix in (".NS", ".BO", ".ns", ".bo"):
        if ticker.upper().endswith(suffix.upper()):
            return ticker[: -len(suffix)].upper()
    return ticker.upper()


def _to_iso_date(date_str: str) -> str:
    """Convert any reasonable date string to yyyy-mm-dd."""
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}")


def _nse_date(date_str: str) -> str:
    """Convert ISO date (yyyy-mm-dd) to NSE format (dd-mm-yyyy)."""
    return datetime.strptime(_to_iso_date(date_str), "%Y-%m-%d").strftime("%d-%m-%Y")


# ── Cached OHLCV (shared between stock data and indicator fetchers) ──


def _fetch_nse_ohlcv(symbol_nse: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Hit NSE historical API and return a DataFrame with yfinance-compatible columns.

    Column mapping (NSE API → standard):
        CH_TIMESTAMP        → Date
        CH_OPENING_PRICE    → Open
        CH_TRADE_HIGH_PRICE → High
        CH_TRADE_LOW_PRICE  → Low
        CH_CLOSING_PRICE    → Close
        CH_TOT_TRADED_QTY   → Volume
    """
    from nsepython import equity_history  # optional import

    nse_start = _nse_date(start_date)
    nse_end = _nse_date(end_date)

    raw = equity_history(symbol_nse, "EQ", nse_start, nse_end)

    if raw is None or (isinstance(raw, pd.DataFrame) and raw.empty):
        raise RuntimeError(
            f"NSE returned no data for {symbol_nse} ({start_date} → {end_date})"
        )

    # The first call to equity_history may return a dict with an error key
    # when NSE blocks the request.  nsepython's nsefetch returns {} on failure.
    if isinstance(raw, dict):
        if raw.get("error"):
            raise RuntimeError(f"NSE API error for {symbol_nse}: {raw.get('error')}")
        if not raw:
            raise RuntimeError(
                f"NSE returned empty response for {symbol_nse}. "
                "NSE may be blocking automated access from your IP."
            )
        raw = pd.DataFrame.from_records(raw.get("data", []))

    if raw.empty:
        raise RuntimeError(f"NSE returned no records for {symbol_nse}")

    # Rename NSE columns to standard OHLCV
    col_map = {
        "CH_TIMESTAMP": "Date",
        "CH_OPENING_PRICE": "Open",
        "CH_TRADE_HIGH_PRICE": "High",
        "CH_TRADE_LOW_PRICE": "Low",
        "CH_CLOSING_PRICE": "Close",
        "CH_TOT_TRADED_QTY": "Volume",
    }
    raw = raw.rename(columns=col_map)

    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in raw.columns:
            raw[col] = pd.to_numeric(raw[col], errors="coerce")

    if "Date" in raw.columns:
        raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")

    return raw


# ── Public vendor functions ────────────────────────────────────────


def get_nse_stock_data(
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    """Return OHLCV data for *symbol* as a CSV string (same format as yfinance provider).

    The caller (route_to_vendor) expects a string, and downstream tool nodes
    pipe this directly into the LLM prompt.
    """
    nse_symbol = _to_nse_symbol(symbol)
    iso_start = _to_iso_date(start_date)
    iso_end = _to_iso_date(end_date)

    logger.info("NSE stock data: %s from %s to %s", nse_symbol, iso_start, iso_end)

    df = _fetch_nse_ohlcv(nse_symbol, start_date, end_date)

    # Round to 2 decimal places for cleaner LLM input
    for col in ("Open", "High", "Low", "Close"):
        if col in df.columns:
            df[col] = df[col].round(2)

    csv_string = df.to_csv(index=False)

    header = (
        f"# NSE stock data for {nse_symbol} ({symbol}) from {iso_start} to {iso_end}\n"
        f"# Total records: {len(df)}\n"
        f"# Source: NSE India (via nsepython)\n\n"
    )
    return header + csv_string


def get_nse_indicators(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int = 30,
) -> str:
    """Compute a single technical indicator using pandas-ta fed by NSE OHLCV.

    Reuses the same pandas-ta pipeline as the yfinance and nse_http providers,
    but sources the underlying OHLCV from NSE via nsepython.
    """
    import pandas as pd
    from datetime import datetime
    from tradingagents.dataflows.config import get_config
    from tradingagents.dataflows.pandasta_utils import compute_indicator, format_indicator_text

    config = get_config()
    nse_symbol = _to_nse_symbol(symbol)
    iso_curr = _to_iso_date(curr_date)

    lookback_start = (
        datetime.strptime(iso_curr, "%Y-%m-%d")
        - pd.DateOffset(days=look_back_days * 3)
    ).strftime("%Y-%m-%d")

    df_nse = _fetch_nse_ohlcv(nse_symbol, lookback_start, curr_date)
    if df_nse.empty:
        raise RuntimeError(f"No NSE OHLCV data available for {nse_symbol}")

    result = compute_indicator(df_nse, indicator.strip().lower())
    if result is None:
        raise ValueError(f"Could not compute indicator '{indicator}' for {nse_symbol}")

    return format_indicator_text(result, indicator.strip().lower(), look_back_days)


def get_nse_live_quote(symbol: str) -> str:
    """Return a human-readable live quote string for *symbol*.

    Only used when the agent explicitly asks for a live price.  Falls back
    to a descriptive error message when NSE blocks the request.
    """
    from nsepython import nse_quote  # optional import

    nse_symbol = _to_nse_symbol(symbol)

    try:
        payload = nse_quote(nse_symbol)
    except Exception as exc:
        return (
            f"# NSE live quote for {nse_symbol}: unavailable\n"
            f"# Error: {exc}\n"
            f"# NSE blocks automated requests from many IPs. "
            f"Consider using yfinance as a fallback."
        )

    if not payload or not isinstance(payload, dict):
        return (
            f"# NSE live quote for {nse_symbol}: no data returned\n"
            f"# NSE may be blocking automated access from this IP."
        )

    price_info = payload.get("priceInfo", payload)

    lines = [f"# NSE Live Quote: {nse_symbol}"]
    for key in (
        "lastPrice",
        "open",
        "dayHigh",
        "dayLow",
        "previousClose",
        "totalTradedVolume",
        "pChange",
        "totalBuyQuantity",
        "totalSellQuantity",
    ):
        val = price_info.get(key, "N/A")
        label = key.replace("totalTradedVolume", "volume").replace("pChange", "change%")
        lines.append(f"{label}: {val}")

    return "\n".join(lines)


# ── HTTP sidecar client (stock-nse-india Node.js service) ─────────

# Base URL of the stock-nse-india API server.  Override with the
# NSE_SIDECAR_URL environment variable.
_NSE_HTTP_BASE = os.environ.get("NSE_SIDECAR_URL", "http://localhost:3009")


def _nse_http_get(path: str, params: dict | None = None) -> dict:
    """Thin wrapper around requests.get for the stock-nse-india REST API."""
    import requests

    url = f"{_NSE_HTTP_BASE}{path}"
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json() if r.text else {}
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"NSE HTTP sidecar unreachable at {_NSE_HTTP_BASE}: {exc}")


def get_nse_http_stock_data(
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    """Return OHLCV CSV from the stock-nse-india historical API.

    Calls ``GET /api/equity/historical/{symbol}?dateStart=...&dateEnd=...``
    and converts the NSE bhavcopy fields into the standard OHLCV CSV format
    expected by the vendor routing layer.
    """
    nse_symbol = _to_nse_symbol(symbol)
    iso_start = _to_iso_date(start_date)
    iso_end = _to_iso_date(end_date)

    payload = _nse_http_get(
        f"/api/equity/historical/{nse_symbol}",
        params={"dateStart": iso_start, "dateEnd": iso_end},
    )

    # The API returns an array of per-day objects with NSE bhavcopy field names.
    # Handle nested structure: payload may be [{data: [...], meta: {...}}, ...]
    all_rows: list[dict] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and "data" in item:
                all_rows.extend(item["data"])
            elif isinstance(item, dict):
                all_rows.append(item)
        rows = all_rows
    elif isinstance(payload, dict):
        rows = payload.get("data", [])
    if isinstance(rows, dict):
        rows = [rows]

    if not rows:
        raise RuntimeError(
            f"NSE HTTP sidecar returned no records for {nse_symbol} "
            f"({iso_start} → {iso_end})"
        )

    records: list[dict] = []
    for row in rows:
        date_val = row.get("mtimestamp", row.get("CH_TIMESTAMP", ""))
        records.append(
            {
                "Date": date_val,
                "Open": float(row.get("chOpeningPrice", row.get("CH_OPENING_PRICE", 0)) or 0),
                "High": float(row.get("chTradeHighPrice", row.get("CH_TRADE_HIGH_PRICE", 0)) or 0),
                "Low": float(row.get("chTradeLowPrice", row.get("CH_TRADE_LOW_PRICE", 0)) or 0),
                "Close": float(row.get("chClosingPrice", row.get("CH_CLOSING_PRICE", 0)) or 0),
                "Volume": int(row.get("chTotTradedQty", row.get("CH_TOT_TRADED_QTY", 0)) or 0),
            }
        )

    if not records:
        raise RuntimeError(f"No valid OHLCV records for {nse_symbol}")

    import pandas as pd
    df = pd.DataFrame(records)

    for col in ("Open", "High", "Low", "Close"):
        df[col] = df[col].round(2)

    csv_string = df.to_csv(index=False)
    header = (
        f"# NSE stock data for {nse_symbol} ({symbol}) from {iso_start} to {iso_end}\n"
        f"# Total records: {len(df)}\n"
        f"# Source: NSE India (via stock-nse-india sidecar)\n\n"
    )
    return header + csv_string


def get_nse_http_indicators(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int = 30,
) -> str:
    """Compute technical indicators from NSE HTTP sidecar OHLCV via pandas-ta."""
    import pandas as pd
    from tradingagents.dataflows.pandasta_utils import compute_indicator, format_indicator_text

    nse_symbol = _to_nse_symbol(symbol)
    iso_curr = _to_iso_date(curr_date)

    lookback_start = (
        pd.Timestamp(iso_curr) - pd.DateOffset(days=look_back_days * 3)
    ).strftime("%Y-%m-%d")

    payload = _nse_http_get(
        f"/api/equity/historical/{nse_symbol}",
        params={"dateStart": lookback_start, "dateEnd": iso_curr},
    )

    all_rows: list[dict] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and "data" in item:
                all_rows.extend(item["data"])
            elif isinstance(item, dict):
                all_rows.append(item)
        rows = all_rows
    elif isinstance(payload, dict):
        rows = payload.get("data", [])
    if isinstance(rows, dict):
        rows = [rows]

    if not rows:
        raise RuntimeError(f"No NSE HTTP OHLCV for {nse_symbol}")

    records: list[dict] = []
    for row in rows:
        records.append(
            {
                "date": row.get("mtimestamp", row.get("CH_TIMESTAMP", "")),
                "open": float(row.get("chOpeningPrice", 0) or 0),
                "high": float(row.get("chTradeHighPrice", 0) or 0),
                "low": float(row.get("chTradeLowPrice", 0) or 0),
                "close": float(row.get("chClosingPrice", 0) or 0),
                "volume": int(row.get("chTotTradedQty", 0) or 0),
            }
        )

    df = pd.DataFrame(records)

    result = compute_indicator(df, indicator.strip().lower())
    if result is None:
        raise ValueError(f"Could not compute indicator '{indicator}' for {nse_symbol}")

    return format_indicator_text(result, indicator.strip().lower(), look_back_days)


def get_nse_http_live_quote(symbol: str) -> str:
    """Return a human-readable live quote from the sidecar."""
    nse_symbol = _to_nse_symbol(symbol)
    payload = _nse_http_get(f"/api/equity/{nse_symbol}")

    price_info = payload.get("priceInfo", payload)
    if not isinstance(price_info, dict):
        return f"# NSE HTTP quote for {nse_symbol}: unexpected response format"

    lines = [f"# NSE Live Quote: {nse_symbol} (via stock-nse-india)"]
    for key, label in (
        ("lastPrice", "Last Price"),
        ("open", "Open"),
        ("dayHigh", "Day High"),
        ("dayLow", "Day Low"),
        ("previousClose", "Prev Close"),
        ("totalTradedVolume", "Volume"),
        ("pChange", "Change %"),
    ):
        val = price_info.get(key)
        if val is not None:
            lines.append(f"{label}: {val}")

    info = payload.get("info", {})
    company = info.get("companyName")
    if company:
        lines.insert(1, f"Company: {company}")

    return "\n".join(lines)


# ── Legacy stubs (non-core, keep for backward compat) ──────────────


def get_fii_dii_activity(date: str) -> str:
    """Get FII/DII buy/sell activity for a given date."""
    try:
        from nsepython import nse_fiidii
        data = nse_fiidii()
        if data and isinstance(data, dict):
            return (
                f"FII/DII activity for {date}:\n"
                f"FII Gross Purchase: {data.get('fiiGrossPurch', 'N/A')} Cr\n"
                f"FII Gross Sales: {data.get('fiiGrossSales', 'N/A')} Cr\n"
                f"FII Net: {data.get('fiiNetValue', 'N/A')} Cr\n"
                f"DII Gross Purchase: {data.get('diiGrossPurch', 'N/A')} Cr\n"
                f"DII Gross Sales: {data.get('diiGrossSales', 'N/A')} Cr\n"
                f"DII Net: {data.get('diiNetValue', 'N/A')} Cr\n"
                f"Source: NSE India (via nsepython)"
            )
    except Exception:
        pass

    return (
        f"FII/DII activity data for {date} is currently unavailable. "
        "Check https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/ "
        "for the latest data. Live FII/DII data may also be available via the "
        "backend's /api/fii-dii/today endpoint if nsepython is accessible."
    )


def get_bulk_block_deals(symbol: str, start_date: str, end_date: str) -> str:
    """Get bulk and block deal data for a symbol."""
    nse_symbol = _to_nse_symbol(symbol)
    try:
        from nsepython import get_bulkdeals, get_blockdeals
        bulk = get_bulkdeals()
        block = get_blockdeals()
        return (
            f"# Bulk Deals\n{bulk}\n\n"
            f"# Block Deals\n{block}\n\n"
            f"Source: NSE India (via nsepython)"
        )
    except Exception:
        return (
            f"Bulk/block deals data for {nse_symbol} is currently unavailable. "
            "This feature requires nsepython library access."
        )


def get_delivery_percentage(symbol: str, date: str) -> str:
    """Get delivery percentage data for a symbol."""
    nse_symbol = _to_nse_symbol(symbol)
    try:
        from nsepython import nsefetch
        payload = nsefetch(
            f"https://www.nseindia.com/api/quote-equity?symbol={nse_symbol}"
        )
        if payload:
            sec = payload.get("securityWiseDP", {})
            return (
                f"Delivery % for {nse_symbol}: {sec.get('deliveryPercentage', 'N/A')}%\n"
                f"Deliverable Qty: {sec.get('deliveryQuantity', 'N/A')}\n"
                f"Traded Qty: {sec.get('tradedQuantity', 'N/A')}\n"
                f"Source: NSE India (via nsepython)"
            )
    except Exception:
        pass

    return (
        f"Delivery percentage data for {nse_symbol} on {date} is unavailable. "
        "This feature requires nsepython library access."
    )
