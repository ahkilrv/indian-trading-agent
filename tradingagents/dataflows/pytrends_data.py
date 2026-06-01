"""Google Trends data provider — lightweight direct HTTPS client.

Google Trends does not offer an official free API.  The explore endpoint
requires cookies, rotating tokens, and an IP that has not been rate-limited.
When the API is reachable this module returns rich interest-over-time data;
when blocked it returns a descriptive fallback message so the agent can
continue without the data.

To enable reliable Trends access, set one of these environment variables:

    SERPAPI_KEY         —  SerpAPI key for Google Trends (serpapi.com)
    TRENDS_PROXY        —  HTTPS proxy URL to route Trends requests through

Without either configured the module degrades gracefully.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── Ticker → search phrase mapping ──────────────────────────────────

_INDIAN_STOCK_PHRASES: dict[str, str] = {
    "RELIANCE": "Reliance Industries share",
    "TCS": "TCS share price",
    "INFY": "Infosys share",
    "HDFCBANK": "HDFC Bank share",
    "ICICIBANK": "ICICI Bank share",
    "TECHM": "Tech Mahindra share",
    "WIPRO": "Wipro share price",
    "BHARTIARTL": "Bharti Airtel share",
    "SBIN": "SBI share price",
    "ITC": "ITC share",
    "LT": "L&T share price",
    "AXISBANK": "Axis Bank share",
    "KOTAKBANK": "Kotak Mahindra Bank share",
    "HINDUNILVR": "Hindustan Unilever share",
    "MARUTI": "Maruti Suzuki share",
    "SUNPHARMA": "Sun Pharma share",
    "TATAMOTORS": "Tata Motors share",
    "TATASTEEL": "Tata Steel share",
    "BAJFINANCE": "Bajaj Finance share",
    "NTPC": "NTPC share",
    "POWERGRID": "Power Grid share",
    "ASIANPAINT": "Asian Paints share",
    "TITAN": "Titan Company share",
    "M&M": "Mahindra Mahindra share",
    "ULTRACEMCO": "UltraTech Cement share",
    "JSWSTEEL": "JSW Steel share",
    "ADANIENT": "Adani Enterprises share",
    "ADANIPORTS": "Adani Ports share",
    "NESTLEIND": "Nestle India share",
    "BAJAJFINSV": "Bajaj Finserv share",
    "HCLTECH": "HCL Technologies share",
    "ONGC": "ONGC share",
    "COALINDIA": "Coal India share",
    "BPCL": "BPCL share",
    "DRREDDY": "Dr Reddys share",
    "CIPLA": "Cipla share",
    "GRASIM": "Grasim share",
    "EICHERMOT": "Eicher Motors share",
    "BRITANNIA": "Britannia share",
    "DIVISLAB": "Divi's Laboratories share",
    "HEROMOTOCO": "Hero MotoCorp share",
}


def _ticker_to_phrase(ticker: str) -> str:
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")
    return _INDIAN_STOCK_PHRASES.get(bare, f"{bare} share")


def _try_serpapi(keyword: str, timeframe: str) -> Optional[dict]:
    """Use SerpAPI to fetch Google Trends data. Returns parsed results or None."""
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        return None

    try:
        # Map our timeframe to SerpAPI's date parameter
        # SerpAPI expects: 'past 7 days', 'past 30 days', 'past 90 days'
        date_map = {
            "today 7-d": "now 7-d",
            "today 1-m": "today 1-m",
            "today 3-m": "today 3-m",
        }
        date = date_map.get(timeframe, "today 3-m")

        resp = requests.get(
            "https://serpapi.com/search",
            params={
                "engine": "google_trends",
                "q": keyword,
                "geo": "IN",
                "date": date,
                "api_key": api_key,
            },
            timeout=15,
        )
        data = resp.json()
        if "interest_over_time" in data:
            return data
    except Exception as exc:
        logger.warning("SerpAPI Trends failed: %s", exc)
    return None


def _try_direct_api(keyword: str, timeframe: str) -> Optional[dict]:
    """Hit the Google Trends explore API directly.  Uses a requests Session
    with a browser-like fingerprint.  Returns parsed data or None when blocked
    (Google rate-limits aggressively — 429 / 400 after a few calls)."""
    proxies = {}
    proxy_url = os.environ.get("TRENDS_PROXY")
    if proxy_url:
        proxies = {"https": proxy_url}

    try:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
            }
        )

        # Prime cookies
        session.get("https://trends.google.com", timeout=10, proxies=proxies)

        req_payload = {
            "comparisonItem": [
                {"keyword": keyword, "geo": "IN", "time": timeframe}
            ],
            "category": 0,
            "property": "",
        }

        resp = session.get(
            "https://trends.google.com/trends/api/explore",
            params={
                "hl": "en-IN",
                "tz": "-330",
                "req": json.dumps(req_payload),
            },
            headers={
                "Referer": "https://trends.google.com/trends/explore",
                "Accept": "application/json",
            },
            timeout=15,
            proxies=proxies,
        )

        if resp.status_code != 200:
            return None

        text = resp.text
        if text.startswith(")]}'"):
            text = text[5:]
        return json.loads(text)
    except Exception as exc:
        logger.warning("Google Trends direct API failed: %s", exc)
        return None


def get_trends_data(ticker: str, timeframe: str = "today 3-m") -> str:
    """Fetch Google Trends interest-over-time data for *ticker*.

    Tries, in order:
      1. SerpAPI (if SERPAPI_KEY is set)
      2. Direct API (if TRENDS_PROXY is configured)
      3. Graceful fallback message

    Returns a formatted report string for the Social Media Analyst.
    """
    phrase = _ticker_to_phrase(ticker)
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")

    tf_map = {"today 3-m": "today 3-m", "today 1-m": "today 1-m", "today 7-d": "today 7-d"}
    tf = tf_map.get(timeframe, "today 3-m")

    lines: list[str] = [
        f"# Google Trends: {phrase}",
        f"# Ticker: {bare}  |  Timeframe: {timeframe}  |  Region: India",
        "",
    ]

    # Try SerpAPI first (most reliable)
    data = _try_serpapi(phrase, tf)
    source = "SerpAPI"

    if data is None:
        # Try direct API (needs fresh IP / proxy)
        data = _try_direct_api(phrase, tf)
        source = "Google Trends"

    if data is None:
        lines.append("## Google Trends data not available")
        lines.append("  Google rate-limits automated requests.")
        lines.append("")
        lines.append("  To enable Trends data, configure one of:")
        lines.append("  - SERPAPI_KEY environment variable (serpapi.com)")
        lines.append("  - TRENDS_PROXY environment variable (HTTPS proxy URL)")
        lines.append("")
        lines.append("  Without Trends data, assess social sentiment")
        lines.append("  using the available news and RSI-divergence signals.")
        return "\n".join(lines)

    # Parse trend data
    try:
        # SerpAPI format — returns hourly for 7-d, daily for 1-m / 3-m
        if "interest_over_time" in data:
            iot = data["interest_over_time"].get("timeline_data", [])
            if iot:
                all_values = [(p.get("date", ""), p.get("values", [{}])[0].get("extracted_value", 0)) for p in iot]
                lines.append("## Interest Over Time (via SerpAPI)")
        else:
            # Direct API format
            widgets = data.get("widgets", [])
            ts_widget = next((w for w in widgets if w.get("id") == "TIMESERIES"), None)
            if ts_widget is None:
                lines.append("## No time-series data available")
                return "\n".join(lines)

            token = ts_widget.get("token", "")
            session = requests.Session()
            ts_resp = session.get(
                "https://trends.google.com/trends/api/widgetdata/multiline",
                params={"hl": "en-IN", "tz": "-330", "req": json.dumps({"time": tf, "resolution": "DAY", "locale": "en-IN", "comparisonItem": [{"geo": {}, "complexKeywordsRestriction": {"keyword": [{"type": "RAW", "value": phrase}]}}], "requestOptions": {"property": "", "backend": "IZG", "category": 0}, "token": token})},
                timeout=15,
            )
            ts_text = ts_resp.text
            if ts_text.startswith(")]}'"):
                ts_text = ts_text[5:]
            ts_data = json.loads(ts_text)
            rows = ts_data.get("default", {}).get("timelineData", [])
            all_values = [(r.get("formattedTime", ""), r.get("value", [0])[0]) for r in rows[-14:]]
            lines.append("## Interest Over Time (via Google Trends)")

        if all_values:
            # Determine granularity: 7-d → hourly (show 24h), 1-m/3-m → daily (show 14d)
            is_hourly = len(all_values) > 50  # 7-d hourly ≈168 pts, 1-m daily ≈30 pts
            show_count = 24 if is_hourly else 14
            values = all_values[-show_count:]

            current = values[-1][1] if values else 0
            lookback = min(24 if is_hourly else 7, len(values) - 1)
            prev_avg = sum(v[1] for v in values[-(lookback + 1):-1]) / max(1, lookback) if len(values) > 1 else current
            is_spiking = current > prev_avg * 2.0 and current > 20

            avg_label = "24h avg" if is_hourly else "7-day avg"
            lines.append(f"  Current: {current} / 100")
            lines.append(f"  {avg_label}: {prev_avg:.1f}")
            lines.append(f"  Spike: {'YES (>2x avg)' if is_spiking else 'No'}")
            lines.append("")
            lines.append("  Recent trend:")

            # For hourly, compress to daily buckets for readability
            if is_hourly:
                from collections import defaultdict
                daily: dict[str, list[int]] = defaultdict(list)
                for dt, val in values:
                    day = dt.split("at")[0].strip().split(",")[0].strip()
                    daily[day].append(val)
                for day, vals in list(daily.items()):
                    peak = max(vals)
                    avg_d = sum(vals) / len(vals)
                    bar = "█" * int(peak / 5) if peak else ""
                    lines.append(f"    {day}: peak {peak:3d}  avg {avg_d:.0f}  {bar}")
            else:
                for dt, val in values[-7:]:
                    bar = "█" * int(val / 5) if val else ""
                    lines.append(f"    {dt}: {val:3d} {bar}")
        else:
            lines.append("  No data points returned.")
    except Exception as exc:
        logger.warning("Trends parse failed for %s: %s", bare, exc)
        lines.append(f"## Parse error: {exc}")

    return "\n".join(lines)
