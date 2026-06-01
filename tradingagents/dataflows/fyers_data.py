"""Fyers API data flow for Indian stock market (NSE/BSE).

Replaces Yahoo Finance / Alpha Vantage as the primary data source
for OHLCV candles, technical indicators, and live quotes.

Requires fyers-apiv3 package and the following environment variables:
    FYERS_APP_ID       — Fyers API app ID
    FYERS_SECRET_KEY   — Fyers API secret key
    FYERS_REDIRECT_URI — OAuth redirect URI (default: https://trade.fyers.in/api-login/redirect-uri/index.html)
"""

from __future__ import annotations

import json
import os
import time
import warnings
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Module-level singleton so interface.py can call plain functions
# ---------------------------------------------------------------------------
_fyers_instance: Optional["FyersDataFlow"] = None


def _get_instance() -> "FyersDataFlow":
    """Return (and lazily initialise) the module-level FyersDataFlow singleton."""
    global _fyers_instance
    if _fyers_instance is None:
        _fyers_instance = FyersDataFlow()
    return _fyers_instance


# ── public functions matching the existing vendor interface ──────────────────

def get_fyers_stock_data(
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    """Fetch daily OHLCV candles via Fyers and return as a CSV string.

    Signature matches :func:`tradingagents.dataflows.y_finance.get_YFin_data_online`
    so it can be plugged straight into ``VENDOR_METHODS``.
    """
    return _get_instance().get_stock_data(symbol, start_date, end_date)


def get_fyers_indicators(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int = 30,
) -> str:
    """Compute a stockstats indicator using Fyers-sourced daily OHLCV data.

    Signature matches
    :func:`tradingagents.dataflows.y_finance.get_stock_stats_indicators_window`.
    """
    return _get_instance().get_indicators(symbol, indicator, curr_date, look_back_days)


def get_fyers_quote(symbol: str) -> dict:
    """Fetch a live market quote from Fyers."""
    return _get_instance().get_quote(symbol)


# ── token persistence ────────────────────────────────────────────────────────

_TOKEN_PATH = os.path.join(
    os.path.expanduser("~"), ".tradingagents", "fyers_token.json"
)


def _load_token() -> Optional[str]:
    """Load a cached access token from disk, validating it hasn't expired."""
    try:
        with open(_token_path := _TOKEN_PATH) as fh:
            data = json.load(fh)
        if data.get("expires_at", 0) > time.time() + 60:
            return data["access_token"]
        # Token expired — delete file so we re-auth
        os.remove(_token_path)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def _save_token(access_token: str, expires_in: int = 86400) -> None:
    """Persist token to disk with an expiry timestamp."""
    os.makedirs(os.path.dirname(_TOKEN_PATH), exist_ok=True)
    with open(_TOKEN_PATH, "w") as fh:
        json.dump(
            {
                "access_token": access_token,
                "expires_at": time.time() + expires_in - 120,
            },
            fh,
        )


# ── ticker helpers ───────────────────────────────────────────────────────────

# Strip common exchange suffixes used by yfinance so we're left with the
# base symbol (e.g. "RELIANCE.NS" → "RELIANCE").
_NSE_SUFFIXES = {".NS", ".BO"}


def _strip_suffix(ticker: str) -> str:
    upper = ticker.strip().upper()
    for s in _NSE_SUFFIXES:
        if upper.endswith(s):
            return upper[: -len(s)]
    return upper


# Recognised index symbols (plain names, no exchange suffix needed).
_INDICES: dict[str, str] = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "NIFTY50": "NSE:NIFTY50-INDEX",
    "NIFTY 50": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:BANKNIFTY-INDEX",
    "NIFTY BANK": "NSE:BANKNIFTY-INDEX",
    "SENSEX": "BSE:SENSEX-INDEX",
    "BSESENSEX": "BSE:SENSEX-INDEX",
}


def to_fyers_symbol(ticker: str) -> str:
    """Convert a human-readable ticker to the Fyers symbol format.

    >>> to_fyers_symbol("RELIANCE")
    'NSE:RELIANCE-EQ'
    >>> to_fyers_symbol("HDFCBANK.NS")
    'NSE:HDFCBANK-EQ'
    >>> to_fyers_symbol("NIFTY 50")
    'NSE:NIFTY50-INDEX'
    """
    base = _strip_suffix(ticker)

    # Check for indices
    if base in _INDICES:
        return _INDICES[base]

    # Default: NSE equity cash segment
    return f"NSE:{base}-EQ"


def _fyers_resolution(interval: str) -> str:
    """Map a human-friendly interval to a Fyers resolution string.

    Supported values: '1', '5', '15', '30', '60', '1D', 'D', 'W'.
    """
    mapping: dict[str, str] = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "60m": "60",
        "1h": "60",
        "1D": "1D",
        "D": "1D",
        "1d": "1D",
        "d": "1D",
        "1W": "W",
        "W": "W",
        "1w": "W",
        "w": "W",
    }
    norm = interval.strip().upper() if interval[0].isalpha() else interval.strip()
    if norm in mapping:
        return mapping[norm]
    # Accept raw numeric values like "15" directly
    if norm.isdigit():
        return norm
    raise ValueError(f"Unsupported interval: {interval!r}")


# ── main class ───────────────────────────────────────────────────────────────


class FyersDataFlow:
    """Data-fetch layer backed by the Fyers API (https://api.fyers.in).

    Typical usage::

        flow = FyersDataFlow()
        flow.authenticate()               # ← OAuth flow (cached)
        df = flow.get_historical_data("HDFCBANK", "2026-05-01", "2026-05-27")
        quote = flow.get_quote("TCS")
    """

    def __init__(self) -> None:
        self._app_id: str = os.environ.get("FYERS_APP_ID", "")
        self._secret: str = os.environ.get("FYERS_SECRET_KEY", "")
        self._redirect: str = os.environ.get(
            "FYERS_REDIRECT_URI",
            "https://trade.fyers.in/api-login/redirect-uri/index.html",
        )
        self._client: object = None  # fyersModel.FyersModel instance
        self._access_token: Optional[str] = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self, force: bool = False) -> None:
        """Obtain or refresh a Fyers access token.

        On first run an OAuth flow is triggered (a browser window opens).
        The token is cached to ``~/.tradingagents/fyers_token.json`` and
        reused until expiry.

        Parameters
        ----------
        force : bool
            If ``True``, ignore any cached token and re-authenticate.
        """
        if not self._app_id or not self._secret:
            raise RuntimeError(
                "FYERS_APP_ID and FYERS_SECRET_KEY must be set in the environment "
                "or .env file."
            )

        # Try cached token first
        if not force:
            cached = _load_token()
            if cached:
                self._access_token = cached
                self._init_client()
                return

        self._do_oauth()

    def _do_oauth(self) -> None:
        """Interactive OAuth 2.0 flow for Fyers using SessionModel (v3 API)."""
        warnings.filterwarnings("ignore", category=DeprecationWarning)

        # Lazy import so fyers-apiv3 is only required when this data source is used
        from fyers_apiv3 import fyersModel

        # Step 1: Create a SessionModel for the OAuth handshake
        session = fyersModel.SessionModel(
            client_id=self._app_id,
            secret_key=self._secret,
            redirect_uri=self._redirect,
            response_type="code",
            grant_type="authorization_code",
        )

        # Step 2: Generate auth URL and get the code
        auth_url = session.generate_authcode()
        print(f"\n[Fyers] Opening browser for OAuth…\n{auth_url}\n")
        try:
            import webbrowser as _wb

            _wb.open(auth_url)
        except Exception:
            pass

        auth_code = input("[Fyers] Paste the auth code from the redirect URL: ").strip()
        session.set_token(auth_code)

        # Step 3: Exchange code for access token
        token_response = session.generate_token()
        self._access_token = token_response["access_token"]
        _save_token(self._access_token, expires_in=86400)
        print("[Fyers] ✓ Authenticated.")
        self._init_client()

    def _init_client(self) -> None:
        """Create a :class:`fyersModel.FyersModel` instance from the stored token."""
        from fyers_apiv3 import fyersModel

        self._client = fyersModel.FyersModel(
            client_id=self._app_id,
            token=self._access_token,
            log_path=os.path.join(
                os.path.expanduser("~"), ".tradingagents", "fyers_logs"
            ),
        )

    # ------------------------------------------------------------------
    # Historical candles
    # ------------------------------------------------------------------

    def get_historical_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str = "1D",
    ) -> pd.DataFrame:
        """Fetch historical OHLCV candles from Fyers.

        Parameters
        ----------
        symbol : str
            Human ticker (e.g. ``"HDFCBANK"``) — automatically converted to
            Fyers format.
        start_date : str
            ``YYYY-MM-DD``
        end_date : str
            ``YYYY-MM-DD``
        interval : str
            Resolution: ``"1"``, ``"5"``, ``"15"``, ``"30"``, ``"60"``,
            ``"1D"`` (default), ``"W"``.

        Returns
        -------
        pd.DataFrame
            Columns: ``open, high, low, close, volume``.
            Index is a ``DatetimeIndex`` with IST timezone **removed** (to
            match the existing yfinance-based interface).
        """
        if self._client is None:
            self.authenticate()

        fy_symbol = to_fyers_symbol(symbol)
        resolution = _fyers_resolution(interval)

        # Fyers expects DD/MM/YYYY or YYYY-MM-DD depending on API version;
        # the v3 API accepts YYYY-MM-DD.
        range_from = start_date  # YYYY-MM-DD
        range_to = end_date

        params = {
            "symbol": fy_symbol,
            "resolution": resolution,
            "date_format": "1",  # YYYY-MM-DD
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": "0",
        }

        response = self._client.history(data=params)
        if response.get("s") != "ok":
            msg = response.get("message", str(response))
            raise RuntimeError(f"Fyers history API error: {msg}")

        candles = response.get("candles", [])
        if not candles:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"]
            )

        # Fyers returns candles as [timestamp, open, high, low, close, volume]
        df = pd.DataFrame(
            candles, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df.set_index("timestamp", inplace=True)
        df.index = df.index.tz_convert("Asia/Kolkata")
        # Remove tz info for consistency with yfinance output
        df.index = df.index.tz_localize(None)
        df.index.name = "Date"

        # Float for price columns
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype(float).round(2)
        df["volume"] = df["volume"].astype(int)

        return df[["open", "high", "low", "close", "volume"]]

    # ------------------------------------------------------------------
    # Live quote
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str) -> dict:
        """Fetch a live Level-1 market quote.

        Parameters
        ----------
        symbol : str
            Human ticker (e.g. ``"TCS"``).

        Returns
        -------
        dict
            Keys: ``symbol, ltp, open, high, low, close, volume, change,
            change_pct, bid, ask, spread``.
        """
        if self._client is None:
            self.authenticate()

        fy_symbol = to_fyers_symbol(symbol)
        response = self._client.quotes(data={"symbols": fy_symbol})

        if response.get("s") != "ok":
            msg = response.get("message", str(response))
            raise RuntimeError(f"Fyers quote API error: {msg}")

        data = (response.get("d", []) or [{}])[0]
        if not data:
            return {"symbol": fy_symbol, "ltp": 0, "error": "No data"}

        ltp = data.get("ltp", 0)

        # Compute change from previous close
        prev_close = data.get("prev_close", ltp)
        change = ltp - prev_close if prev_close else 0
        change_pct = round(change / prev_close * 100, 2) if prev_close else 0

        spread = (data.get("ask", ltp) or ltp) - (data.get("bid", ltp) or ltp)

        return {
            "symbol": fy_symbol,
            "ltp": ltp,
            "open": data.get("open", 0),
            "high": data.get("high", 0),
            "low": data.get("low", 0),
            "close": prev_close,
            "volume": data.get("volume", 0),
            "change": round(change, 2),
            "change_pct": change_pct,
            "bid": data.get("bid", 0),
            "ask": data.get("ask", 0),
            "spread": round(spread, 2),
        }

    # ------------------------------------------------------------------
    # Interface-compatible methods (used by VENDOR_METHODS in interface.py)
    # ------------------------------------------------------------------

    def get_stock_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> str:
        """Fetch daily OHLCV data and return as a CSV string.

        This matches the signature of
        :func:`~tradingagents.dataflows.y_finance.get_YFin_data_online`
        so it can be dropped into ``VENDOR_METHODS`` without any other
        changes.
        """
        # Validate date format (matching y_finance behaviour)
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")

        df = self.get_historical_data(symbol, start_date, end_date, interval="1D")

        if df.empty:
            return (
                f"No data found for symbol '{symbol}' "
                f"between {start_date} and {end_date}"
            )

        # Build CSV with header (matching yfinance output style)
        csv_body = df.to_csv()
        header = (
            f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
            f"# Total records: {len(df)}\n"
            f"# Data retrieved on: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')} "
            f"(via Fyers)\n\n"
        )
        return header + csv_body

    def get_indicators(
        self,
        symbol: str,
        indicator: str,
        curr_date: str,
        look_back_days: int = 30,
    ) -> str:
        """Compute a technical indicator using stockstats from Fyers OHLCV data.

        Matches the signature of
        :func:`~tradingagents.dataflows.y_finance.get_stock_stats_indicators_window`.
        """
        from datetime import timedelta

        from dateutil.relativedelta import relativedelta
        from stockstats import wrap

        end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        before_dt = end_dt - relativedelta(days=look_back_days)

        # Buffer: fetch extra 10 days so stockstats can compute longer-window
        # indicators (e.g. 50 SMA) without NaN holes.
        fetch_start = (before_dt - timedelta(days=60)).strftime("%Y-%m-%d")

        try:
            df = self.get_historical_data(
                symbol, fetch_start, curr_date, interval="1D"
            )
        except Exception:
            # Fallback: try the original date range
            df = self.get_historical_data(
                symbol,
                before_dt.strftime("%Y-%m-%d"),
                curr_date,
                interval="1D",
            )

        if df.empty:
            return (
                f"No data available for {symbol} around {curr_date} "
                f"(lookback: {look_back_days} days)."
            )

        # stockstats expects columns: Date, Open, High, Low, Close, Volume
        # and the index must be a column called "Date".
        df = df.reset_index()
        df.rename(
            columns={
                "Date": "Date",
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            },
            inplace=True,
        )

        wrapped = wrap(df)

        # Collect values for the requested date range
        current_dt = end_dt
        date_values: list[tuple[str, str]] = []
        while current_dt >= before_dt:
            date_str = current_dt.strftime("%Y-%m-%d")
            try:
                # stockstats uses integer-based index; look up by date label
                mask = df["Date"] == date_str
                if mask.any():
                    idx = int(mask.idxmax())
                    val = wrapped.get(indicator, idx)
                    date_values.append(
                        (date_str, str(val) if pd.notna(val) else "N/A")
                    )
                else:
                    date_values.append((date_str, "N/A: Not a trading day"))
            except Exception:
                date_values.append((date_str, "N/A"))
            current_dt = current_dt - relativedelta(days=1)

        # Indicator descriptions (matching y_finance.py)
        descriptions: dict[str, str] = {
            "close_50_sma": "50 SMA: A medium-term trend indicator.",
            "close_200_sma": "200 SMA: A long-term trend benchmark.",
            "close_10_ema": "10 EMA: A responsive short-term average.",
            "macd": "MACD: Momentum via differences of EMAs.",
            "macds": "MACD Signal: An EMA smoothing of the MACD line.",
            "macdh": "MACD Histogram: Shows the gap between MACD and signal.",
            "rsi": "RSI: Measures momentum to flag overbought/oversold conditions.",
            "boll": "Bollinger Middle: A 20 SMA, basis for Bollinger Bands.",
            "boll_ub": "Bollinger Upper Band: ~2 std above middle.",
            "boll_lb": "Bollinger Lower Band: ~2 std below middle.",
            "atr": "ATR: Averages true range to measure volatility.",
            "vwma": "VWMA: A moving average weighted by volume.",
            "mfi": "MFI: Money Flow Index using price and volume.",
        }

        ind_string = "\n".join(
            f"{d}: {v}" for d, v in reversed(date_values)
        )

        return (
            f"## {indicator} values from "
            f"{before_dt.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
            f"{ind_string}\n\n"
            f"{descriptions.get(indicator, 'No description available.')}"
        )