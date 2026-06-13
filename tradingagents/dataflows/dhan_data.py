"""DhanHQ broker API as a data source (NSE/BSE OHLCV + live quotes).

Uses Dhan's REST API v2 — requires an active Dhan account with Data API
subscription.  Two authentication methods, tried in order:

1. **TOTP auto-generation** (recommended).  Set ``DHAN_CLIENT_ID``,
   ``DHAN_PIN``, and ``DHAN_TOTP_SECRET`` (from web.dhan.co → TOTP setup).
   Tokens are generated automatically using RFC 6238 TOTP — no manual steps.

2. **Manual access token** (fallback).  Set ``DHAN_ACCESS_TOKEN`` directly
   from web.dhan.co → Generate Token.  Expires every 24 hours.

Reference: https://dhanhq.co/docs/v2/
"""

from __future__ import annotations

import base64
import csv
import hmac
import logging
import os
import struct
import time
from datetime import datetime
from io import StringIO
from typing import Optional

import pandas as pd
import requests
from tradingagents.dataflows.utils import get_prev_trading_day

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

_BASE_URL = "https://api.dhan.co/v2"
_AUTH_URL = "https://auth.dhan.co"
_INSTRUMENTS_CSV_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
_INSTRUMENTS_CACHE_TTL = 3600  # 1 hour — refresh instrument list periodically

# ── Token cache ──────────────────────────────────────────────────────

_cached_token: str = ""
_cached_token_expiry: float = 0.0  # epoch seconds — when the token expires
_TOKEN_REFRESH_MARGIN = 300  # refresh 5 minutes before expiry
_TOKEN_COOLDOWN = 120  # Dhan allows only 1 token generation per 2 minutes
_last_token_attempt: float = 0.0  # cooldown tracker


# ── TOTP (RFC 6238) — pure stdlib, no external deps ─────────────────


def _generate_totp(secret: str, interval: int = 30, digits: int = 6) -> str:
    """Generate a Time-based One-Time Password (RFC 6238).

    Compatible with Google Authenticator, Authy, and the TOTP codes that
    Dhan's auth.dhan.co endpoint expects.

    Args:
        secret: Base32-encoded TOTP secret (from Dhan TOTP setup QR).
        interval: Time step in seconds (default 30).
        digits: Number of digits in the code (default 6).
    """
    key = base64.b32decode(secret.upper().replace(" ", ""))
    counter = int(time.time()) // interval
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, "sha1").digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


# ── Token acquisition ────────────────────────────────────────────────


def _acquire_token_from_dhan(client_id: str, pin: str, totp_secret: str) -> tuple[str, float]:
    """Call Dhan's auth endpoint to get a fresh access token + expiry time.

    Returns:
        (access_token, expiry_epoch) tuple.
    """
    totp = _generate_totp(totp_secret)
    url = (
        f"{_AUTH_URL}/app/generateAccessToken"
        f"?dhanClientId={client_id}&pin={pin}&totp={totp}"
    )

    logger.info("Requesting Dhan access token via TOTP ...")
    resp = requests.post(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    token = data.get("accessToken", "")
    expiry_str = data.get("expiryTime", "")

    if not token:
        raise RuntimeError(
            f"Dhan token generation failed: {data.get('errorMessage', data)}"
        )

    # Parse expiry: "2026-01-01T00:00:00.000" → epoch seconds
    try:
        expiry_dt = datetime.strptime(expiry_str[:19], "%Y-%m-%dT%H:%M:%S")
        expiry_epoch = expiry_dt.timestamp()
    except (ValueError, IndexError):
        # If parsing fails, assume 24 hours from now
        expiry_epoch = time.time() + 86400

    ttl_hours = (expiry_epoch - time.time()) / 3600
    logger.info(
        "Dhan token acquired — expires in %.1f hours (%s)",
        ttl_hours,
        expiry_str,
    )
    return token, expiry_epoch


def _get_access_token() -> str:
    """Return a valid Dhan access token (cached or freshly generated).

    Priority:
    1. Cached TOTP-generated token (if not expired)
    2. DHAN_ACCESS_TOKEN env var (manual mode)
    3. Auto-generate via TOTP (DHAN_PIN + DHAN_TOTP_SECRET)

    Token generation is rate-limited by Dhan to once every 2 minutes.
    If the cached token has expired but we are within the cooldown,
    the stale token is returned as best-effort.
    """
    global _cached_token, _cached_token_expiry, _last_token_attempt

    # 1. Return cached token if still valid (with refresh margin)
    if _cached_token and time.time() < (_cached_token_expiry - _TOKEN_REFRESH_MARGIN):
        return _cached_token

    # 2. Manual token from env (user manages renewal)
    manual_token = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()
    if manual_token:
        _cached_token = manual_token
        _cached_token_expiry = time.time() + 86400  # assume 24h
        return manual_token

    # 3. TOTP auto-generation
    client_id = os.environ.get("DHAN_CLIENT_ID", "").strip()
    pin = os.environ.get("DHAN_PIN", "").strip()
    totp_secret = os.environ.get("DHAN_TOTP_SECRET", "").strip()

    if client_id and pin and totp_secret:
        # Respect Dhan's 2-min token generation cooldown
        elapsed = time.time() - _last_token_attempt
        if elapsed < _TOKEN_COOLDOWN:
            if _cached_token:
                # Return stale token — better than nothing
                logger.debug(
                    "Token cooldown active (%.0fs left) — reusing cached token",
                    _TOKEN_COOLDOWN - elapsed,
                )
                return _cached_token
            # First-time after startup: wait until cooldown passes
            wait = _TOKEN_COOLDOWN - elapsed
            logger.info("Waiting %.0fs for Dhan token cooldown ...", wait)
            time.sleep(wait)

        _last_token_attempt = time.time()
        try:
            token, expiry = _acquire_token_from_dhan(client_id, pin, totp_secret)
        except Exception:
            if _cached_token:
                logger.warning(
                    "Token generation failed — reusing stale cached token"
                )
                return _cached_token
            raise

        _cached_token = token
        _cached_token_expiry = expiry
        return token

    # Not configured at all
    raise RuntimeError(
        "Dhan API credentials not configured.\n"
        "Option A (auto): Set DHAN_CLIENT_ID, DHAN_PIN, DHAN_TOTP_SECRET\n"
        "Option B (manual): Set DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN"
    )


def _invalidate_token() -> None:
    """Force a fresh token on the next API call (called on 401 responses).

    Does NOT clear cooldown tracker — that stays to avoid rate-limiting.
    """
    global _cached_token_expiry
    _cached_token_expiry = 0.0  # force refresh on next call
    logger.debug("Dhan token marked for refresh")


# ── Auth header helpers ─────────────────────────────────────────────────


def _get_auth_headers() -> dict:
    """Return authentication headers for Dhan API calls.

    Acquires a token automatically if not already cached.
    """
    client_id = os.environ.get("DHAN_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError("DHAN_CLIENT_ID not set in environment")
    return {
        "accept": "application/json",
        "Content-Type": "application/json",
        "access-token": _get_access_token(),
        "client-id": client_id,
    }


def _is_configured() -> bool:
    """Check if Dhan credentials are available (any method)."""
    has_manual = bool(os.environ.get("DHAN_CLIENT_ID")) and bool(
        os.environ.get("DHAN_ACCESS_TOKEN")
    )
    has_totp = (
        bool(os.environ.get("DHAN_CLIENT_ID"))
        and bool(os.environ.get("DHAN_PIN"))
        and bool(os.environ.get("DHAN_TOTP_SECRET"))
    )
    return has_manual or has_totp


# ── Ticker helpers ───────────────────────────────────────────────────


def _to_nse_symbol(ticker: str) -> str:
    """Strip exchange suffixes."""
    return ticker.split(".")[0].strip().upper()


def _to_iso_date(date_str: str) -> str:
    """Normalize to YYYY-MM-DD."""
    fmts = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"]
    for fmt in fmts:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}")


# ── Instrument mapping (ticker → Dhan security ID) ─────────────────


_security_id_cache: dict[str, str] = {}
_cache_timestamp: float = 0.0


def _find_col(headers: list[str], candidates: list[str]) -> int:
    """Find the index of the first matching column name."""
    for i, h in enumerate(headers):
        if h.strip() in candidates:
            return i
    raise ValueError(f"CSV missing expected column: {candidates}")


def _load_instrument_map() -> dict[str, str]:
    """Download and parse the Dhan instrument master CSV.

    Returns ``{SYMBOL_NAME: security_id}`` for NSE Equity instruments.
    The CSV is cached in memory for 1 hour.
    """
    global _security_id_cache, _cache_timestamp

    if _security_id_cache and (time.time() - _cache_timestamp) < _INSTRUMENTS_CACHE_TTL:
        return _security_id_cache

    logger.info("Downloading Dhan instrument master CSV ...")
    try:
        resp = requests.get(_INSTRUMENTS_CSV_URL, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        logger.error("Failed to download Dhan instrument CSV: %s", exc)
        if _security_id_cache:
            return _security_id_cache  # reuse stale cache
        return {}

    # The compact CSV columns (comma-separated):
    # 0: SEM_EXM_EXCH_ID  (NSE/BSE/MCX)
    # 1: SEM_SEGMENT      (E=Equity, D=Derivatives, C=Currency, M=Commodity)
    # 2: SEM_SMST_SECURITY_ID → ** security ID **
    # 3: SEM_INSTRUMENT_NAME
    # 4: SEM_EXPIRY_CODE
    # 5: SEM_TRADING_SYMBOL  → ** ticker ** (e.g. "RELIANCE")
    # 14: SEM_SERIES  (EQ=active equity, BE=blocked)
    # 15: SM_SYMBOL_NAME  → full company name

    reader = csv.reader(StringIO(resp.text), delimiter=",")
    new_cache: dict[str, str] = {}

    try:
        header_row = next(reader)
        col_exchange = _find_col(header_row, ["SEM_EXM_EXCH_ID"])
        col_segment = _find_col(header_row, ["SEM_SEGMENT"])
        col_sec_id = _find_col(header_row, ["SEM_SMST_SECURITY_ID", "SEM_SM_KEY"])
        col_ticker = _find_col(header_row, ["SEM_TRADING_SYMBOL"])
        col_series = _find_col(header_row, ["SEM_SERIES"])
    except StopIteration:
        logger.error("Dhan instrument CSV is empty")
        return _security_id_cache

    for row in reader:
        if len(row) <= max(col_exchange, col_segment, col_sec_id, col_ticker):
            continue
        exchange = row[col_exchange].strip()
        segment = row[col_segment].strip()
        ticker = row[col_ticker].strip()
        security_id = row[col_sec_id].strip()
        series = row[col_series].strip() if col_series < len(row) else "EQ"

        # Filter: NSE Equity, active series only (EQ = actively traded)
        if exchange != "NSE" or segment != "E":
            continue
        if series != "EQ":
            continue
        if not ticker or not security_id:
            continue

        new_cache[ticker.upper()] = security_id

    _security_id_cache = new_cache
    _cache_timestamp = time.time()
    logger.info("Loaded %d NSE Equity instruments from Dhan master", len(new_cache))
    return _security_id_cache


def _get_security_id(ticker: str) -> tuple[str, str]:
    """Resolve a ticker to (security_id, exchange_segment).

    Returns (security_id, "NSE_EQ") for NSE equity instruments.
    """
    instrument_map = _load_instrument_map()
    symbol = _to_nse_symbol(ticker)
    security_id = instrument_map.get(symbol)
    if not security_id:
        raise RuntimeError(
            f"Dhan instrument not found for '{symbol}'. "
            "Is it an active NSE equity?"
        )
    return security_id, "NSE_EQ"


# ── Dhan REST client ─────────────────────────────────────────────────


class DhanClient:
    """Thin wrapper around requests for Dhan API calls.

    No singleton needed — functions are stateless.  Auth headers are
    rebuilt on every call (token may have rotated between calls).
    """

    _last_request_time: float = 0.0

    @classmethod
    def get(cls, path: str, data: dict | None = None) -> dict:
        """POST to Dhan API (all data endpoints use POST)."""
        url = f"{_BASE_URL}{path}"

        # Rate limit: 5 req/s for data APIs, be conservative at 4 req/s
        elapsed = time.time() - cls._last_request_time
        if elapsed < 0.25:
            time.sleep(0.25 - elapsed)

        token_refreshed = False
        for attempt in range(3):
            # Rebuild auth headers each attempt (token may have expired)
            headers = _get_auth_headers()

            try:
                resp = requests.post(url, headers=headers, json=data or {}, timeout=30)
                if resp.status_code == 401:
                    if not token_refreshed:
                        logger.info("Dhan token expired — refreshing via TOTP")
                        _invalidate_token()
                        token_refreshed = True
                        continue
                    raise RuntimeError(
                        "Dhan access token expired or invalid — token refresh failed. "
                        "Check DHAN_CLIENT_ID, DHAN_PIN, and DHAN_TOTP_SECRET."
                    )
                if resp.status_code == 429:
                    wait = 1.0 * (attempt + 1)
                    logger.warning("Dhan rate-limited, waiting %.1fs", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                cls._last_request_time = time.time()
                return resp.json()
            except requests.exceptions.RequestException:
                if attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))

        raise RuntimeError(f"Dhan API unreachable: {path}")


# ── Public vendor functions ───────────────────────────────────────────


def get_dhan_stock_data(
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    """Return daily OHLCV CSV from Dhan's historical charts API.

    If the historical data doesn't include the current trading day,
    appends a live quote record so the analyst always sees the latest price.

    Signature matches ``get_nse_http_stock_data`` / ``get_yfinance_stock_data``.
    """
    security_id, exchange_segment = _get_security_id(symbol)
    iso_start = _to_iso_date(start_date)
    iso_end = _to_iso_date(end_date)

    payload = DhanClient.get(
        "/charts/historical",
        {
            "securityId": security_id,
            "exchangeSegment": exchange_segment,
            "instrument": "EQUITY",
            "expiryCode": 0,
            "oi": False,
            "fromDate": iso_start,
            "toDate": iso_end,
        },
    )

    # Dhan returns parallel arrays: open[], high[], low[], close[], volume[], timestamp[]
    opens = payload.get("open", [])
    highs = payload.get("high", [])
    lows = payload.get("low", [])
    closes = payload.get("close", [])
    volumes = payload.get("volume", [])
    timestamps = payload.get("timestamp", [])

    if not opens:
        raise RuntimeError(
            f"Dhan returned no OHLCV data for {symbol} ({iso_start} → {iso_end})"
        )

    records: list[dict] = []
    for i in range(len(opens)):
        records.append(
            {
                "Date": datetime.fromtimestamp(timestamps[i]).strftime("%Y-%m-%d")
                if i < len(timestamps)
                else "",
                "Open": round(opens[i], 2),
                "High": round(highs[i], 2),
                "Low": round(lows[i], 2),
                "Close": round(closes[i], 2),
                "Volume": volumes[i] if i < len(volumes) else 0,
            }
        )

    df = pd.DataFrame(records)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # If the latest historical record is before today, try to supplement
    # with the live quote so the analyst sees the current trading day's data.
    # Use end_date (snapped to the last trading day) rather than datetime.now()
    # so the date is consistent with the requested date range and avoids
    # requesting a live quote on non-trading days (weekends).
    quote_date = get_prev_trading_day(datetime.now()).strftime("%Y-%m-%d")
    latest_date = df["Date"].max() if "Date" in df.columns and not df.empty else ""
    live_quote_appended = False
    if latest_date < quote_date:
        try:
            quote = DhanClient.get(
                "/marketfeed/ohlc",
                {exchange_segment: [int(security_id)]},
            )
            qdata = quote.get("data", {})
            seg_data = qdata.get(exchange_segment, {})
            inst = seg_data.get(security_id, seg_data)
            if inst:
                ltp = inst.get("last_price")
                ohlc = inst.get("ohlc", {})
                if ltp is not None:
                    records.append({
                        "Date": quote_date,
                        "Open": round(float(ohlc.get("open", ltp)), 2) if ohlc.get("open") else round(float(ltp), 2),
                        "High": round(float(ohlc.get("high", ltp)), 2) if ohlc.get("high") else round(float(ltp), 2),
                        "Low": round(float(ohlc.get("low", ltp)), 2) if ohlc.get("low") else round(float(ltp), 2),
                        "Close": round(float(ltp), 2),
                        "Volume": 0,
                    })
                    df = pd.DataFrame(records)
                    for col in ("Open", "High", "Low", "Close", "Volume"):
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors="coerce")
                    live_quote_appended = True
        except Exception:
            # Live quote is best-effort; if it fails, return historical data as-is
            pass

    csv_string = df.to_csv(index=False)
    source_label = "DhanHQ API + Live Quote" if live_quote_appended else "DhanHQ API"
    header = (
        f"# Dhan stock data for {symbol} from {iso_start} to {iso_end}\n"
        f"# Total records: {len(df)}\n"
        f"# Source: {source_label}\n\n"
    )
    return header + csv_string


def get_dhan_indicators(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int = 30,
) -> str:
    """Compute a technical indicator from Dhan OHLCV via pandas-ta."""
    from tradingagents.dataflows.pandasta_utils import compute_indicator, format_indicator_text

    iso_curr = _to_iso_date(curr_date)
    lookback_start = (
        pd.Timestamp(iso_curr) - pd.DateOffset(days=look_back_days * 3)
    ).strftime("%Y-%m-%d")

    security_id, exchange_segment = _get_security_id(symbol)

    payload = DhanClient.get(
        "/charts/historical",
        {
            "securityId": security_id,
            "exchangeSegment": exchange_segment,
            "instrument": "EQUITY",
            "expiryCode": 0,
            "oi": False,
            "fromDate": lookback_start,
            "toDate": iso_curr,
        },
    )

    opens = payload.get("open", [])
    highs = payload.get("high", [])
    lows = payload.get("low", [])
    closes = payload.get("close", [])
    volumes = payload.get("volume", [])
    timestamps = payload.get("timestamp", [])

    if not opens:
        raise RuntimeError(f"Dhan returned no OHLCV for {symbol}")

    records: list[dict] = []
    for i in range(len(opens)):
        records.append(
            {
                "Date": datetime.fromtimestamp(timestamps[i]).strftime("%Y-%m-%d")
                if i < len(timestamps)
                else "",
                "Open": opens[i],
                "High": highs[i],
                "Low": lows[i],
                "Close": closes[i],
                "Volume": volumes[i] if i < len(volumes) else 0,
            }
        )

    df = pd.DataFrame(records)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    result = compute_indicator(df, indicator.strip().lower())
    if result is None:
        raise ValueError(
            f"Could not compute indicator '{indicator}' for {symbol}. "
            "Insufficient columns or data — do NOT retry this indicator."
        )

    return format_indicator_text(result, indicator.strip().lower(), look_back_days)


def get_dhan_live_quote(symbol: str) -> str:
    """Return a human-readable live quote from Dhan's market feed API.

    Uses ``/marketfeed/ohlc`` which returns LTP + OHLC for the day.
    """
    security_id, exchange_segment = _get_security_id(symbol)

    try:
        payload = DhanClient.get(
            "/marketfeed/ohlc",
            {exchange_segment: [int(security_id)]},
        )
    except Exception as exc:
        return (
            f"# Dhan live quote for {symbol}: unavailable\n"
            f"# Error: {exc}\n"
            f"# Falling through to next vendor."
        )

    data = payload.get("data", {})
    segment_data = data.get(exchange_segment, {})
    instrument_data = segment_data.get(security_id, segment_data)

    if not instrument_data:
        return f"# Dhan live quote for {symbol}: no data returned"

    ltp = instrument_data.get("last_price", "N/A")
    ohlc = instrument_data.get("ohlc", {})

    lines = [f"# Dhan Live Quote: {symbol} (DhanHQ API)"]
    lines.append(f"Last Price: {ltp}")
    if ohlc:
        lines.append(f"Open: {ohlc.get('open', 'N/A')}")
        lines.append(f"High: {ohlc.get('high', 'N/A')}")
        lines.append(f"Low: {ohlc.get('low', 'N/A')}")
        lines.append(f"Prev Close: {ohlc.get('close', 'N/A')}")

    return "\n".join(lines)


def get_dhan_live_quote_full(symbol: str) -> str:
    """Return a detailed live quote with market depth from Dhan.

    Uses ``/marketfeed/quote`` which includes depth, volume, OI, circuit limits.
    """
    security_id, exchange_segment = _get_security_id(symbol)

    try:
        payload = DhanClient.get(
            "/marketfeed/quote",
            {exchange_segment: [int(security_id)]},
        )
    except Exception as exc:
        return (
            f"# Dhan full quote for {symbol}: unavailable\n"
            f"# Error: {exc}"
        )

    data = payload.get("data", {})
    segment_data = data.get(exchange_segment, {})
    inst = segment_data.get(security_id, segment_data)

    if not inst:
        return f"# Dhan full quote for {symbol}: no data returned"

    ohlc = inst.get("ohlc", {})
    lines = [f"# Dhan Full Quote: {symbol} (DhanHQ API)"]

    for key, label in (
        ("last_price", "Last Price"),
        ("average_price", "VWAP"),
        ("net_change", "Net Change"),
    ):
        val = inst.get(key)
        if val is not None:
            lines.append(f"{label}: {val}")

    lines.append("")
    lines.append("## OHLC")
    for key, label in (
        ("open", "Open"),
        ("high", "High"),
        ("low", "Low"),
        ("close", "Close"),
    ):
        val = ohlc.get(key)
        if val is not None:
            lines.append(f"{label}: {val}")

    lines.append("")
    lines.append("## Volume & Depth")
    lines.append(f"Volume: {inst.get('volume', 'N/A')}")
    lines.append(f"Buy Quantity: {inst.get('buy_quantity', 'N/A')}")
    lines.append(f"Sell Quantity: {inst.get('sell_quantity', 'N/A')}")
    lines.append(f"Lower Circuit: {inst.get('lower_circuit_limit', 'N/A')}")
    lines.append(f"Upper Circuit: {inst.get('upper_circuit_limit', 'N/A')}")

    depth = inst.get("depth", {})
    buy_depth = depth.get("buy", [])
    sell_depth = depth.get("sell", [])

    if buy_depth:
        lines.append("")
        lines.append("## Top 5 Bid")
        for i, bid in enumerate(buy_depth[:5]):
            if bid.get("price"):
                lines.append(
                    f"  {bid['price']} x {bid.get('quantity', 0)} "
                    f"({bid.get('orders', 0)} orders)"
                )

    if sell_depth:
        lines.append("")
        lines.append("## Top 5 Ask")
        for i, ask in enumerate(sell_depth[:5]):
            if ask.get("price"):
                lines.append(
                    f"  {ask['price']} x {ask.get('quantity', 0)} "
                    f"({ask.get('orders', 0)} orders)"
                )

    return "\n".join(lines)
