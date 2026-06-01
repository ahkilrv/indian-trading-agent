"""Technical indicator computation using pandas-ta (130+ indicators).

Drop-in replacement for the stockstats-based pipeline.  Callers pass
OHLCV DataFrames and receive indicator values as pandas Series.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)

# ── Indicator metadata (description, usage, tips) ──────────────────

INDICATOR_META: dict[str, str] = {
    # Moving Averages
    "sma_50": (
        "50 SMA: A medium-term trend indicator. "
        "Usage: Identify trend direction and serve as dynamic support/resistance. "
        "Tips: It lags price; combine with faster indicators for timely signals."
    ),
    "sma_200": (
        "200 SMA: A long-term trend benchmark. "
        "Usage: Confirm overall market trend and identify golden/death cross setups. "
        "Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries."
    ),
    "ema_20": (
        "20 EMA: A responsive short-term average. "
        "Usage: Capture quick shifts in momentum and potential entry points. "
        "Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals."
    ),
    "ema_50": (
        "50 EMA: Medium-term exponential moving average. "
        "Usage: Trend direction and dynamic support/resistance. "
        "Tips: More responsive than SMA; crossovers with EMA 20 signal momentum shifts."
    ),
    # MACD
    "macd": (
        "MACD: Computes momentum via differences of EMAs. "
        "Usage: Look for crossovers and divergence as signals of trend changes. "
        "Tips: Confirm with other indicators in low-volatility or sideways markets."
    ),
    "macd_signal": (
        "MACD Signal: An EMA smoothing of the MACD line. "
        "Usage: Use crossovers with the MACD line to trigger trades. "
        "Tips: Should be part of a broader strategy to avoid false positives."
    ),
    "macd_histogram": (
        "MACD Histogram: Shows the gap between the MACD line and its signal. "
        "Usage: Visualize momentum strength and spot divergence early. "
        "Tips: Can be volatile; complement with additional filters in fast-moving markets."
    ),
    # Momentum
    "rsi": (
        "RSI: Measures momentum to flag overbought/oversold conditions. "
        "Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. "
        "Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis."
    ),
    "stoch": (
        "Stochastic Oscillator: Compares closing price to price range. "
        "Usage: Overbought > 80, oversold < 20. Watch for crossovers. "
        "Tips: Works best in ranging markets; can give false signals in strong trends."
    ),
    "cci": (
        "CCI: Commodity Channel Index measures price deviation from average. "
        "Usage: Above +100 = overbought, below -100 = oversold. "
        "Tips: Use with trend indicators to avoid counter-trend trades."
    ),
    "adx": (
        "ADX: Average Directional Index measures trend strength. "
        "Usage: Above 25 = trending market, below 20 = ranging. "
        "Tips: ADX doesn't show direction — use +DI/-DI for that."
    ),
    "willr": (
        "Williams %R: Momentum indicator similar to Stochastic. "
        "Usage: Above -20 = overbought, below -80 = oversold. "
        "Tips: Best combined with trend analysis for confirmation."
    ),
    "roc": (
        "ROC: Rate of Change measures the percentage price change. "
        "Usage: Positive = upward momentum, negative = downward. "
        "Tips: Watch for divergences with price for reversal signals."
    ),
    "mom": (
        "Momentum: Raw price change over N periods. "
        "Usage: Cross above zero = bullish, below = bearish. "
        "Tips: Simple but effective for trend following."
    ),
    # Volatility
    "bollinger": (
        "Bollinger Bands: 20 SMA ± 2 standard deviations. "
        "Usage: Price near upper band = overbought, near lower = oversold. "
        "Tips: Band squeeze signals impending volatility expansion."
    ),
    "bb_upper": (
        "Bollinger Upper Band: Typically 2 standard deviations above the middle line. "
        "Usage: Signals potential overbought conditions and breakout zones. "
        "Tips: Confirm signals with other tools; prices may ride the band in strong trends."
    ),
    "bb_lower": (
        "Bollinger Lower Band: Typically 2 standard deviations below the middle line. "
        "Usage: Indicates potential oversold conditions. "
        "Tips: Use additional analysis to avoid false reversal signals."
    ),
    "bb_width": (
        "Bollinger Band Width: Measures the distance between upper and lower bands. "
        "Usage: Narrowing bands = potential breakout, widening = increased volatility. "
        "Tips: Look for squeezes as setups for directional trades."
    ),
    "atr": (
        "ATR: Averages true range to measure volatility. "
        "Usage: Set stop-loss levels and adjust position sizes based on current market volatility. "
        "Tips: It's a reactive measure, so use it as part of a broader risk management strategy."
    ),
    "kc": (
        "Keltner Channels: EMA ± ATR multiplier. "
        "Usage: Similar to Bollinger but uses ATR instead of standard deviation. "
        "Tips: Keltner breakouts tend to be more reliable than Bollinger in trending markets."
    ),
    # Volume-Based
    "vwap": (
        "VWAP: Volume Weighted Average Price. "
        "Usage: Institutional benchmark; price above VWAP = bullish intraday. "
        "Tips: Most useful on intraday timeframes; resets daily."
    ),
    "mfi": (
        "MFI: Money Flow Index uses price and volume to measure pressure. "
        "Usage: Overbought > 80, oversold < 20. Confirm trends or reversals. "
        "Tips: Divergence between price and MFI can indicate reversals."
    ),
    "obv": (
        "OBV: On-Balance Volume relates volume to price changes. "
        "Usage: Rising OBV confirms uptrend, falling confirms downtrend. "
        "Tips: Look for OBV divergences from price for early reversal signals."
    ),
    "cmf": (
        "CMF: Chaikin Money Flow measures buying/selling pressure. "
        "Usage: Positive = accumulation, negative = distribution. "
        "Tips: Cross above/below zero can confirm trend changes."
    ),
    "eom": (
        "EOM: Ease of Movement combines price change and volume. "
        "Usage: Positive = prices rising easily, negative = falling with ease. "
        "Tips: High values with low volume can signal reversals."
    ),
    # Trend
    "supertrend": (
        "SuperTrend: Trend-following indicator using ATR. "
        "Usage: Price above = bullish (buy), below = bearish (sell). "
        "Tips: Works well in trending markets; can whipsaw in ranges."
    ),
    "psar": (
        "Parabolic SAR: Stop and reverse indicator. "
        "Usage: Dots below price = uptrend, above = downtrend. "
        "Tips: Best used for trailing stops rather than entry signals."
    ),
    "ichimoku": (
        "Ichimoku Cloud: Multi-component trend system. "
        "Usage: Price above cloud = bullish, below = bearish. "
        "Tips: Cloud thickness indicates support/resistance strength."
    ),
    "dpo": (
        "DPO: Detrended Price Oscillator removes long-term trends. "
        "Usage: Identify short-term cycles and overbought/oversold. "
        "Tips: Useful for swing trading in ranging markets."
    ),
    "trix": (
        "TRIX: Triple-smoothed EMA of price. "
        "Usage: Cross above zero = bullish, below = bearish. "
        "Tips: Very smooth; best for medium-term trend following."
    ),
}


# ── Core computation ───────────────────────────────────────────────


def _prepare_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize an OHLCV DataFrame for pandas-ta.

    Expects columns: Date, Open, High, Low, Close, Volume (or lowercase).
    Returns a DataFrame with lowercase columns and DateTimeIndex.
    """
    df = df.copy()

    # Flatten MultiIndex columns when present (yfinance download artefacts)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Standardise column names
    rename_map = {}
    for std_col in ("open", "high", "low", "close", "volume"):
        for alt in (std_col, std_col.title(), std_col.upper()):
            if alt in df.columns:
                rename_map[alt] = std_col
                break
    if rename_map:
        df = df.rename(columns=rename_map)

    # Parse Date column as index when present
    found_date = False
    for date_col in ("Date", "date", "CH_TIMESTAMP"):
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            if df[date_col].notna().any():
                df = df.dropna(subset=[date_col])
                df = df.set_index(date_col).sort_index()
                found_date = True
                break

    if not found_date and not isinstance(df.index, pd.DatetimeIndex):
        # yfinance data has dates in the index, not a column
        try:
            df.index = pd.to_datetime(df.index)
        except Exception:
            pass

    # Ensure numeric types
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def compute_indicator(
    df: pd.DataFrame,
    indicator: str,
) -> Optional[pd.Series | pd.DataFrame]:
    """Compute a single technical indicator from an OHLCV DataFrame."""
    df = _prepare_ohlcv(df)

    # Drop rows where close is NaN — prevents pandas-ta from failing on
    # incomplete data (e.g. yfinance returns NaN for future/today's close)
    if df.get("close") is not None:
        df = df.dropna(subset=["close"])

    ind = indicator.lower().strip()

    close = df.get("close")
    high = df.get("high")
    low = df.get("low")
    vol = df.get("volume")
    ohlc_ok = all(c is not None for c in (close, high, low))

    # ── Moving Averages ─────────────────────────────────────────
    if ind in ("sma", "sma_50", "close_50_sma"):
        return ta.sma(close, length=50)
    if ind in ("sma_200", "close_200_sma"):
        return ta.sma(close, length=200)
    if ind in ("sma_20"):
        return ta.sma(close, length=20)
    if ind in ("ema", "ema_20", "close_10_ema", "close_20_ema"):
        return ta.ema(close, length=20)
    if ind == "ema_50":
        return ta.ema(close, length=50)
    if ind == "ema_200":
        return ta.ema(close, length=200)
    if ind == "vwma":
        return ta.vwma(close, vol, length=20)

    # ── MACD ────────────────────────────────────────────────────
    if ind == "macd":
        return ta.macd(close)
    if ind in ("macds", "macd_signal"):
        result = ta.macd(close)
        return result.iloc[:, 1] if result is not None else None  # signal line
    if ind in ("macdh", "macd_histogram"):
        result = ta.macd(close)
        return result.iloc[:, 2] if result is not None else None  # histogram

    # ── Momentum ────────────────────────────────────────────────
    if ind == "rsi":
        return ta.rsi(close, length=14)
    if ind == "stoch":
        return ta.stoch(high, low, close) if ohlc_ok else None
    if ind == "cci":
        return ta.cci(high, low, close) if ohlc_ok else None
    if ind == "adx":
        return ta.adx(high, low, close) if ohlc_ok else None
    if ind == "willr":
        return ta.willr(high, low, close) if ohlc_ok else None
    if ind in ("roc",):
        return ta.roc(close, length=10)
    if ind in ("mom",):
        return ta.mom(close, length=10)

    # ── Volatility ──────────────────────────────────────────────
    if ind in ("bollinger", "boll", "bb", "bbands"):
        return ta.bbands(close, length=20)
    if ind in ("boll_ub", "bb_upper"):
        result = ta.bbands(close, length=20)
        return result.iloc[:, 2] if result is not None else None
    if ind in ("boll_lb", "bb_lower"):
        result = ta.bbands(close, length=20)
        return result.iloc[:, 0] if result is not None else None
    if ind in ("bb_width",):
        result = ta.bbands(close, length=20)
        if result is not None:
            return result.iloc[:, 2] - result.iloc[:, 0]
    if ind == "atr":
        return ta.atr(high, low, close, length=14) if ohlc_ok else None
    if ind in ("kc", "keltner"):
        return ta.kc(high, low, close) if ohlc_ok else None

    # ── Volume ──────────────────────────────────────────────────
    if ind == "mfi":
        return ta.mfi(high, low, close, vol, length=14) if (ohlc_ok and vol is not None) else None
    if ind in ("obv",):
        return ta.obv(close, vol) if vol is not None else None
    if ind in ("cmf",):
        return ta.cmf(high, low, close, vol) if (ohlc_ok and vol is not None) else None
    if ind in ("eom",):
        return ta.eom(high, low, close, vol) if (ohlc_ok and vol is not None) else None

    # ── Trend ───────────────────────────────────────────────────
    if ind in ("supertrend",):
        return ta.supertrend(high, low, close) if ohlc_ok else None
    if ind in ("psar",):
        return ta.psar(high, low, close) if ohlc_ok else None
    if ind in ("ichimoku",):
        return ta.ichimoku(high, low, close) if ohlc_ok else None
    if ind in ("dpo",):
        return ta.dpo(close, length=20)
    if ind == "trix":
        return ta.trix(close, length=15)

    # ── Fallback: try to find the indicator by name ─────────────
    func = getattr(ta, ind, None)
    if func is not None and callable(func):
        try:
            return func(close)
        except Exception:
            pass

    return None


def format_indicator_text(
    series: pd.Series | pd.DataFrame,
    indicator: str,
    look_back_days: int,
) -> str:
    """Render indicator values as a human-readable string for LLM prompts."""
    meta = INDICATOR_META.get(indicator.lower(), indicator.upper())
    lines = [f"## {indicator} values", f"{meta}", ""]

    if isinstance(series, pd.DataFrame):
        # Multi-column indicator (e.g. MACD, BB)
        series = series.tail(look_back_days)
        for col in series.columns:
            val = series[col].iloc[-1]
            lines.append(f"  {col}: {val:.2f}")
    elif isinstance(series, pd.Series):
        series = series.dropna().tail(look_back_days)
        for idx, val in series.items():
            lines.append(f"  {idx}: {val:.2f}")
    else:
        lines.append(f"  No data available for {indicator}")

    return "\n".join(lines)
