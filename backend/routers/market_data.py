"""Market data endpoints — stock quotes, charts, indicators, fundamentals, news."""

import math

from fastapi import APIRouter, Query
import yfinance as yf
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from tradingagents.utils.ticker import normalize_ticker

IST = ZoneInfo("Asia/Kolkata")

router = APIRouter(prefix="/api/market-data", tags=["market-data"])

# ── Helpers ──────────────────────────────────────────────────────────


def _yf_safe_ticker(symbol: str):
    """Create a yfinance Ticker, returning None if rate-limited."""
    import yfinance.exceptions
    try:
        return yf.Ticker(symbol)
    except yfinance.exceptions.YFRateLimitError:
        return None
    except Exception:
        return None


def _yf_safe_info(symbol: str) -> dict:
    """Fetch yfinance info safely — returns empty dict on failure."""
    t = _yf_safe_ticker(symbol)
    if t is None:
        return {}
    try:
        return t.info or {}
    except Exception:
        return {}


def _yf_safe_history(symbol: str, **kwargs):
    """Fetch yfinance history safely — returns empty DataFrame on failure."""
    import pandas as pd
    t = _yf_safe_ticker(symbol)
    if t is None:
        return pd.DataFrame()
    try:
        return t.history(**kwargs)
    except Exception:
        return pd.DataFrame()


def _stock_source() -> str:
    """Return human-readable stock data source label."""
    try:
        from tradingagents.dataflows.interface import get_data_source_label
        return get_data_source_label("get_stock_data")
    except Exception:
        return "Yahoo Finance"


def _indicator_source() -> str:
    """Return human-readable indicator data source label."""
    try:
        from tradingagents.dataflows.interface import get_data_source_label
        return get_data_source_label("get_indicators")
    except Exception:
        return "Yahoo Finance"


@router.get("/search")
def search_stocks(q: str = Query("", description="Search query — ticker or company name")):
    """Search Indian stocks by ticker or company name. Typeahead endpoint."""
    from backend.stock_list import search_stocks as _search
    return _search(q)


@router.get("/quote/{ticker}")
def get_quote(ticker: str):
    """Get real-time quote for a ticker."""
    symbol = normalize_ticker(ticker)

    # Try yfinance first (info + history), then fall back to vendor chain
    info = _yf_safe_info(symbol)
    hist = _yf_safe_history(symbol, period="2d")

    if hist.empty or not info:
        # yfinance rate-limited or unavailable — try the vendor chain for chart data
        try:
            from tradingagents.dataflows.interface import route_to_vendor
            csv_data = route_to_vendor(
                "get_stock_data",
                ticker,
                (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
            )
            # Parse CSV to get latest price
            import pandas as pd
            from io import StringIO
            df = pd.read_csv(StringIO(csv_data), comment="#")
            if df.empty:
                return {"ticker": symbol, "error": "No data available", "data_source": _stock_source()}
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last
            price = last.get("Close", last.get("close", 0))
            prev_close = info.get("previousClose") or prev.get("Close", prev.get("close", price))
            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            return {
                "ticker": symbol,
                "name": info.get("shortName", symbol),
                "price": round(float(price), 2) if price else None,
                "change": round(float(change), 2) if price else None,
                "change_percent": round(float(change_pct), 2) if price else None,
                "volume": int(last.get("Volume", last.get("volume", 0))),
                "high": round(float(last.get("High", last.get("high", 0))), 2) or None,
                "low": round(float(last.get("Low", last.get("low", 0))), 2) or None,
                "open": round(float(last.get("Open", last.get("open", 0))), 2) or None,
                "prev_close": round(float(prev_close), 2) if prev_close else None,
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "data_source": _stock_source(),
            }
        except Exception:
            return {"ticker": symbol, "error": "All data sources unavailable", "data_source": _stock_source()}

    current = hist.iloc[-1]
    prev_close = info.get("previousClose") or (hist.iloc[-2]["Close"] if len(hist) > 1 else current["Close"])
    price = current["Close"]
    change = price - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0

    return {
        "ticker": symbol,
        "name": info.get("shortName", symbol),
        "price": round(price, 2),
        "change": round(change, 2),
        "change_percent": round(change_pct, 2),
        "volume": int(current.get("Volume", 0)),
        "high": round(current["High"], 2),
        "low": round(current["Low"], 2),
        "open": round(current["Open"], 2),
        "prev_close": round(prev_close, 2),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "data_source": _stock_source(),
    }


@router.get("/chart/{ticker}")
def get_chart_data(
    ticker: str,
    period: str = Query("3mo", description="1d, 5d, 1mo, 3mo, 6mo, 1y, 2y"),
    interval: str = Query("1d", description="1m, 5m, 15m, 1h, 1d, 1wk"),
):
    """Get OHLCV chart data for a ticker."""
    symbol = normalize_ticker(ticker)
    hist = _yf_safe_history(symbol, period=period, interval=interval)

    if hist.empty:
        return {"error": f"No data for {symbol}", "data": [], "data_source": _stock_source()}

    data = []
    for idx, row in hist.iterrows():
        o, h, l, c = row["Open"], row["High"], row["Low"], row["Close"]
        # Skip rows with NaN OHLCV (yfinance returns NaN for future dates)
        if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in (o, h, l, c)):
            continue
        ts = idx.strftime("%Y-%m-%d") if interval in ("1d", "1wk", "1mo") else idx.isoformat()
        data.append({
            "time": ts,
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": int(row["Volume"]) if not (isinstance(row["Volume"], float) and math.isnan(row["Volume"])) else 0,
        })

    return {
        "ticker": symbol,
        "period": period,
        "interval": interval,
        "data": data,
        "data_source": _stock_source(),
    }


@router.get("/indicators/{ticker}")
def get_indicators(
    ticker: str,
    indicators: str = Query("rsi,macd,boll_ub,boll_lb,close_10_ema,close_50_sma,atr,vwma"),
    lookback_days: int = Query(60),
):
    """Get technical indicators for a ticker."""
    from tradingagents.dataflows.interface import route_to_vendor

    symbol = normalize_ticker(ticker)
    end_date = datetime.now(IST).strftime("%Y-%m-%d")

    results = {}
    for indicator in indicators.split(","):
        indicator = indicator.strip()
        try:
            result = route_to_vendor("get_indicators", symbol, indicator, end_date, lookback_days)
            results[indicator] = result
        except Exception as e:
            results[indicator] = f"Error: {str(e)}"

    return {
        "ticker": symbol,
        "indicators": results,
        "data_source": _indicator_source(),
    }


@router.get("/fundamentals/{ticker}")
def get_fundamentals(ticker: str):
    """Get company fundamentals."""
    symbol = normalize_ticker(ticker)
    t = yf.Ticker(symbol)
    info = t.info

    return {
        "ticker": symbol,
        "name": info.get("shortName", symbol),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "pb_ratio": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "eps": info.get("trailingEps"),
        "roe": info.get("returnOnEquity"),
        "debt_to_equity": info.get("debtToEquity"),
        "revenue": info.get("totalRevenue"),
        "profit_margin": info.get("profitMargins"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "avg_volume": info.get("averageVolume"),
        "beta": info.get("beta"),
        "data_source": _stock_source(),
    }


@router.get("/news/{ticker}")
def get_news(ticker: str, count: int = Query(10)):
    """Get latest news for a ticker."""
    symbol = normalize_ticker(ticker)
    t = yf.Ticker(symbol)
    news = t.get_news(count=count)

    articles = []
    for article in (news or []):
        if "content" in article:
            content = article["content"]
            articles.append({
                "title": content.get("title", ""),
                "summary": content.get("summary", ""),
                "publisher": content.get("provider", {}).get("displayName", "Unknown"),
                "url": (content.get("canonicalUrl") or content.get("clickThroughUrl") or {}).get("url", ""),
                "published_at": content.get("pubDate", ""),
            })
        else:
            articles.append({
                "title": article.get("title", ""),
                "summary": "",
                "publisher": article.get("publisher", "Unknown"),
                "url": article.get("link", ""),
                "published_at": "",
            })

    return {"ticker": symbol, "news": articles}


@router.get("/market-status")
def get_market_status():
    """Get current Indian market status (NIFTY, BANKNIFTY, session)."""
    from tradingagents.utils.market_calendar import get_market_session, is_trading_day

    nifty = yf.Ticker("^NSEI")
    banknifty = yf.Ticker("^NSEBANK")

    nifty_hist = nifty.history(period="2d")
    banknifty_hist = banknifty.history(period="2d")

    def extract_quote(hist, info_ticker):
        if hist.empty:
            return {"price": 0, "change": 0, "change_percent": 0}
        current = hist.iloc[-1]
        prev = hist.iloc[-2]["Close"] if len(hist) > 1 else current["Close"]
        price = current["Close"]
        change = price - prev
        return {
            "price": round(price, 2),
            "change": round(change, 2),
            "change_percent": round(change / prev * 100, 2) if prev else 0,
        }

    return {
        "session": get_market_session(),
        "is_trading_day": is_trading_day(),
        "nifty": extract_quote(nifty_hist, nifty),
        "banknifty": extract_quote(banknifty_hist, banknifty),
        "data_source": _stock_source(),
    }
