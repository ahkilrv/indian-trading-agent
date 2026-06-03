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
    """Get company fundamentals.

    Tries yfinance first (with error handling), then falls back to
    the vendor chain: Alpha Vantage → yfinance.
    """
    symbol = normalize_ticker(ticker)

    # Attempt 1: yfinance with safe wrapper
    info = _yf_safe_info(symbol)
    if info:
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
            "data_source": "Yahoo Finance",
        }

    # Attempt 2: vendor chain (Alpha Vantage → yfinance)
    try:
        from tradingagents.dataflows.interface import route_to_vendor
        from datetime import datetime
        raw = route_to_vendor("get_fundamentals", symbol, datetime.now().strftime("%Y-%m-%d"))

        data = _parse_fundamentals(raw)
        if data and data.get("name"):
            return {
                "ticker": symbol,
                **{k: v for k, v in data.items() if v is not None},
                "data_source": data.get("data_source", "yfinance"),
            }
    except Exception:
        pass

    return {
        "ticker": symbol,
        "name": symbol.removesuffix(".NS").removesuffix(".BO"),
        "sector": None,
        "industry": None,
        "market_cap": None,
        "pe_ratio": None,
        "forward_pe": None,
        "pb_ratio": None,
        "dividend_yield": None,
        "eps": None,
        "roe": None,
        "debt_to_equity": None,
        "revenue": None,
        "profit_margin": None,
        "fifty_two_week_high": None,
        "fifty_two_week_low": None,
        "beta": None,
        "data_source": None,
        "note": "Fundamentals temporarily unavailable — yfinance rate-limited on Render IP. Try again later or use AI Analysis for agent-driven fundamentals.",
    }


_YF_FIELD_MAP = {
    "Name": "name", "Sector": "sector", "Industry": "industry",
    "Market Cap": "market_cap", "PE Ratio (TTM)": "pe_ratio",
    "Forward PE": "forward_pe", "PEG Ratio": "peg_ratio",
    "Price to Book": "pb_ratio", "EPS (TTM)": "eps",
    "Forward EPS": "forward_eps", "Dividend Yield": "dividend_yield",
    "Beta": "beta", "52 Week High": "fifty_two_week_high",
    "52 Week Low": "fifty_two_week_low",
    "50 Day Average": "fifty_day_avg", "200 Day Average": "two_hundred_day_avg",
    "Revenue (TTM)": "revenue", "Gross Profit": "gross_profit",
    "EBITDA": "ebitda", "Net Income": "net_income",
    "Profit Margin": "profit_margin", "Operating Margin": "operating_margin",
    "Return on Equity": "roe", "Return on Assets": "roa",
    "Debt to Equity": "debt_to_equity", "Current Ratio": "current_ratio",
    "Book Value": "book_value", "Free Cash Flow": "free_cash_flow",
    "Stock P/E": "pe_ratio", "Book Value": "book_value",
    "ROCE": "roce", "Face Value": "face_value",
    "High / Low": "high_low",
}

_AV_FIELD_MAP = {
    "Name": "name", "Sector": "sector", "Industry": "industry",
    "PERatio": "pe_ratio", "ForwardPE": "forward_pe",
    "PEGRatio": "peg_ratio", "PriceToBookRatio": "pb_ratio",
    "EPS": "eps", "DividendYield": "dividend_yield",
    "Beta": "beta", "52WeekHigh": "fifty_two_week_high",
    "52WeekLow": "fifty_two_week_low",
    "RevenueTTM": "revenue", "ProfitMargin": "profit_margin",
    "ReturnOnEquityTTM": "roe", "DebtToEquityRatio": "debt_to_equity",
    "MarketCapitalization": "market_cap",
    "OperatingMarginTTM": "operating_margin",
    "BookValue": "book_value",
}


def _parse_fundamentals(raw):
    """Parse fundamentals from Alpha Vantage JSON or yfinance text format."""
    import json
    if isinstance(raw, dict):
        return _remap_fields(raw, _AV_FIELD_MAP, "Alpha Vantage")
    if isinstance(raw, str):
        # Try AV JSON
        if raw.strip().startswith("{"):
            try:
                data = json.loads(raw)
                if data and data.get("Name"):
                    return _remap_fields(data, _AV_FIELD_MAP, "Alpha Vantage")
            except json.JSONDecodeError:
                pass
        # Fallback: yfinance / screener text format
        if raw.startswith("# Company Fundamentals"):
            # Detect source from comment lines
            source = "yfinance"
            for header_line in raw.split("\n")[:5]:
                if "# Source: Screener.in" in header_line:
                    source = "Screener.in"
                    break
            d = {"data_source": source}
            for line in raw.split("\n"):
                line = line.strip()
                if ": " in line and not line.startswith("#"):
                    key, val = line.split(": ", 1)
                    mapped = _YF_FIELD_MAP.get(key)
                    if mapped:
                        d[mapped] = val if mapped in ("name", "sector", "industry") else _safe_float(val)
            if d.get("name") or d.get("pe_ratio") or d.get("market_cap"):
                return d
    return {}


def _remap_fields(data, field_map, source):
    result = {"data_source": source}
    for av_key, out_key in field_map.items():
        val = data.get(av_key)
        if val is not None:
            result[out_key] = _safe_float(val) if out_key not in ("name", "sector", "industry") else val
    return result


def _safe_float(val):
    """Convert a value to float, return None if not possible."""
    if val is None:
        return None
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None


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


@router.get("/debug/sources/{ticker}")
def debug_data_sources(ticker: str):
    """Test all configured data sources and report status for each."""
    from tradingagents.dataflows.interface import route_to_vendor, VENDOR_METHODS, get_data_source_label
    from datetime import datetime, timedelta
    import json, traceback

    symbol = ticker.upper()
    now = datetime.now()
    results = {}

    # 1. Stock data (Dhan → nse_http → yfinance)
    try:
        csv_str = route_to_vendor("get_stock_data", symbol, (now - timedelta(days=30)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"))
        import pandas as pd
        from io import StringIO
        df = pd.read_csv(StringIO(csv_str), comment="#")
        results["get_stock_data"] = {
            "status": "OK",
            "rows": len(df),
            "latest_close": float(df.iloc[-1].get("Close", df.iloc[-1].get("close", 0))),
            "vendors": list(VENDOR_METHODS.get("get_stock_data", {}).keys()),
        }
    except Exception as e:
        results["get_stock_data"] = {"status": "FAIL", "error": str(e), "vendors": list(VENDOR_METHODS.get("get_stock_data", {}).keys())}

    # 2. Fundamentals (Alpha Vantage → yfinance)
    try:
        raw = route_to_vendor("get_fundamentals", symbol, now.strftime("%Y-%m-%d"))
        is_json = isinstance(raw, dict) or (isinstance(raw, str) and raw.strip().startswith("{"))
        if is_json:
            if isinstance(raw, str):
                import json
                data = json.loads(raw)
            else:
                data = raw
            results["get_fundamentals"] = {
                "status": "OK",
                "name": data.get("Name") or data.get("shortName", "(no name)"),
                "sector": data.get("Sector") or data.get("sector"),
                "pe": data.get("PERatio") or data.get("trailingPE"),
                "data_format": "json",
            }
        else:
            preview = raw[:300] if isinstance(raw, str) else str(raw)[:300]
            ticker_name = ""
            pe_val = None
            for line in preview.split("\n"):
                if line.startswith("Name:"):
                    ticker_name = line.split(":", 1)[1].strip()
                elif "PE Ratio" in line:
                    pe_val = line.split(":", 1)[1].strip() if ":" in line else None
            results["get_fundamentals"] = {
                "status": "OK",
                "name": ticker_name or "yfinance text format",
                "pe": pe_val,
                "data_format": "yfinance_text",
                "preview": preview,
            }
    except Exception as e:
        results["get_fundamentals"] = {"status": "FAIL", "error": str(e), "vendors": list(VENDOR_METHODS.get("get_fundamentals", {}).keys())}

    # 3. News (yfinance)
    try:
        from yfinance import Ticker
        t = Ticker(symbol)
        news = t.get_news(count=3)
        results["get_news"] = {
            "status": "OK",
            "articles": len(news or []),
            "sample": (news or [{}])[0].get("title", news[0].get("content", {}).get("title", "")) if news else "none",
            "vendors": list(VENDOR_METHODS.get("get_news", {}).keys()),
        }
    except Exception as e:
        results["get_news"] = {"status": "FAIL", "error": str(e), "vendors": list(VENDOR_METHODS.get("get_news", {}).keys())}

    # 4. RSS ticker news (Google News RSS + ET)
    from tradingagents.dataflows.rss_news import get_rss_ticker_news
    try:
        rss_text = get_rss_ticker_news(symbol)
        total_line = [l for l in rss_text.split("\n") if "Total articles" in l]
        results["get_ticker_news"] = {
            "status": "OK",
            "total_articles": total_line[0] if total_line else "unknown",
            "length_chars": len(rss_text),
        }
    except Exception as e:
        results["get_ticker_news"] = {"status": "FAIL", "error": str(e)}

    # 5. SerpAPI Google News
    from tradingagents.dataflows.serp_news import get_serp_news_data
    try:
        serp_text = get_serp_news_data(symbol)
        total_found = len([l for l in serp_text.split("\n") if l.startswith("  ") and "**" in l])
        results["get_serp_news"] = {
            "status": "OK",
            "articles_found": total_found,
            "length_chars": len(serp_text),
        }
    except Exception as e:
        results["get_serp_news"] = {"status": "FAIL", "error": str(e)}

    # 6. SerpAPI YouTube
    from tradingagents.dataflows.serp_youtube import get_youtube_sentiment_data
    try:
        yt_text = get_youtube_sentiment_data(symbol)
        video_lines = [l for l in yt_text.split("\n") if "Videos Found" in l]
        results["get_youtube_sentiment"] = {
            "status": "OK",
            "summary": video_lines[0] if video_lines else "no videos line",
            "length_chars": len(yt_text),
        }
    except Exception as e:
        results["get_youtube_sentiment"] = {"status": "FAIL", "error": str(e)}

    # 7. SerpAPI Forums
    from tradingagents.dataflows.serp_forums import get_forums_sentiment_data
    try:
        forum_text = get_forums_sentiment_data(symbol)
        disc_lines = [l for l in forum_text.split("\n") if "Discussions Found" in l]
        results["get_forums_sentiment"] = {
            "status": "OK",
            "summary": disc_lines[0] if disc_lines else "no discussions line",
            "length_chars": len(forum_text),
        }
    except Exception as e:
        results["get_forums_sentiment"] = {"status": "FAIL", "error": str(e)}

    # 8. SerpAPI Google Finance
    from tradingagents.dataflows.serp_finance import get_google_finance_data
    try:
        gf_text = get_google_finance_data(symbol)
        price_lines = [l for l in gf_text.split("\n") if "Price:" in l]
        results["get_google_finance"] = {
            "status": "OK",
            "summary": price_lines[0] if price_lines else "no price line",
            "length_chars": len(gf_text),
        }
    except Exception as e:
        results["get_google_finance"] = {"status": "FAIL", "error": str(e)}

    # 9. FII/DII
    from backend.fii_dii import get_today_data, get_recent_history, get_market_bias
    try:
        fiidii_today = get_today_data()
        fiidii_hist = get_recent_history(3)
        fiidii_bias = get_market_bias()
        results["fii_dii"] = {
            "status": "OK",
            "today": {"date": fiidii_today.get("date"), "fii_net": fiidii_today.get("fii_net"), "dii_net": fiidii_today.get("dii_net"), "source": fiidii_today.get("source")} if fiidii_today else "no data",
            "history_days": len(fiidii_hist),
            "bias": fiidii_bias.get("bias"),
        }
    except Exception as e:
        results["fii_dii"] = {"status": "FAIL", "error": str(e)}

    # 10. FII via force_refresh (tests Moneycontrol)
    try:
        fiidii_fresh = get_today_data(force_refresh=True)
        results["fii_dii_force_refresh"] = {
            "status": "OK",
            "date": fiidii_fresh.get("date") if fiidii_fresh else "none",
            "fii_net": fiidii_fresh.get("fii_net") if fiidii_fresh else None,
            "source": fiidii_fresh.get("source") if fiidii_fresh else "none",
        } if fiidii_fresh else {"status": "FAIL", "error": "No data returned from force_refresh"}
    except Exception as e:
        results["fii_dii_force_refresh"] = {"status": "FAIL", "error": str(e)}

    return results


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
