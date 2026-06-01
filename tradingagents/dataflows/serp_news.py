"""SerpAPI Google News client — structured news for the News Analyst.

Provides `get_serp_news_data()` which queries Google News via SerpAPI
for ticker-specific articles sorted by recency.  Returns a formatted
report with article count, source breakdown, and headline sentiment hints.

Requires: SERPAPI_KEY in environment (already in .env).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search"

_INDIAN_FINANCE_SOURCES = {
    "Economic Times",
    "Times of India",
    "Moneycontrol",
    "Livemint",
    "Business Standard",
    "Financial Express",
    "Hindu Business Line",
    "Bloomberg Quint",
    "CNBC TV18",
    "ET Now",
    "NDTV Profit",
    "Zee Business",
    "Reuters",
    "Bloomberg",
    "Fortune India",
    "Forbes India",
    "Inc42",
    "Entrackr",
    "YourStory",
}


def _ticker_to_phrase(ticker: str) -> str:
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")
    phrase_map = {
        "RELIANCE":      "Reliance Industries",
        "TCS":           "Tata Consultancy Services",
        "INFY":          "Infosys",
        "HDFCBANK":      "HDFC Bank",
        "ICICIBANK":     "ICICI Bank",
        "SBIN":          "State Bank of India",
        "TECHM":         "Tech Mahindra",
        "WIPRO":         "Wipro",
        "BHARTIARTL":    "Bharti Airtel",
        "ITC":           "ITC",
        "LT":            "Larsen & Toubro",
        "AXISBANK":      "Axis Bank",
        "KOTAKBANK":     "Kotak Mahindra Bank",
        "HINDUNILVR":    "Hindustan Unilever",
        "MARUTI":        "Maruti Suzuki",
        "SUNPHARMA":     "Sun Pharma",
        "TATAMOTORS":    "Tata Motors",
        "TATASTEEL":     "Tata Steel",
        "BAJFINANCE":    "Bajaj Finance",
        "NTPC":          "NTPC",
        "POWERGRID":     "Power Grid",
        "ASIANPAINT":    "Asian Paints",
        "TITAN":         "Titan",
        "M&M":           "Mahindra & Mahindra",
        "ULTRACEMCO":    "UltraTech Cement",
        "JSWSTEEL":      "JSW Steel",
        "ADANIENT":      "Adani Enterprises",
        "ADANIPORTS":    "Adani Ports",
        "NESTLEIND":     "Nestle India",
        "BAJAJFINSV":    "Bajaj Finserv",
        "HCLTECH":       "HCL Technologies",
        "ONGC":          "ONGC",
        "COALINDIA":     "Coal India",
        "BPCL":          "BPCL",
        "DRREDDY":       "Dr Reddy's",
        "CIPLA":         "Cipla",
        "GRASIM":        "Grasim",
        "EICHERMOT":     "Eicher Motors",
        "BRITANNIA":     "Britannia",
        "DIVISLAB":      "Divi's Laboratories",
        "HEROMOTOCO":    "Hero MotoCorp",
    }
    return phrase_map.get(bare, bare.replace("_", " "))


def _call_serpapi(params: dict) -> Optional[dict]:
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        return None
    params["api_key"] = api_key
    try:
        resp = requests.get(SERPAPI_BASE, params=params, timeout=15)
        data = resp.json()
        if "error" in data:
            logger.warning("SerpAPI error (engine=%s): %s", params.get("engine"), data["error"])
            return None
        return data
    except Exception as exc:
        logger.warning("SerpAPI call failed (engine=%s): %s", params.get("engine"), exc)
        return None


def _sentiment_hint_from_title(title: str) -> str:
    """Crude heuristic: count positive vs negative words in headline."""
    positive = {"rise", "rises", "rally", "gain", "surge", "jump", "upgrade",
                "beat", "outperform", "strong", "boost", "bounce", "bullish",
                "buy", "growth", "positive", "record", "profit"}
    negative = {"fall", "falls", "drop", "plunge", "crash", "downgrade",
                "sink", "loss", "weak", "bearish", "sell", "negative",
                "decline", "slump", "warn", "caution", "risk", "concern"}
    words = title.lower().split()
    pos = sum(1 for w in words if w in positive)
    neg = sum(1 for w in words if w in negative)
    if pos > neg:
        return "[BULLISH]"
    elif neg > pos:
        return "[BEARISH]"
    return "[NEUTRAL]"


def get_serp_news_data(ticker: str, days_back: int = 7) -> str:
    """Fetch structured news from Google News via SerpAPI for *ticker*.

    Returns a formatted markdown report for the News Analyst.
    """
    phrase = _ticker_to_phrase(ticker)
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")

    data = _call_serpapi({
        "engine": "google_news",
        "q": f"{phrase} stock NSE India",
        "gl": "in",
        "hl": "en",
        # so only works with story_token/section_token, not q
    })

    lines = [
        f"# Google News: {phrase}",
        f"# Ticker: {bare}  |  Source: SerpAPI Google News  |  Region: India",
        "",
    ]

    if data is None:
        lines.append("## Google News data not available (SerpAPI)")

    results = data.get("news_results", []) if data else []
    if not results:
        lines.append("  No news articles found for this ticker.")
        return "\n".join(lines)

    # Filter to top 15 articles
    articles = []
    for item in results[:20]:
        # Extract from highlight or direct
        highlight = item.get("highlight", item)
        title = highlight.get("title", item.get("title", ""))
        source_name = ""
        source_info = highlight.get("source", item.get("source", {}))
        if isinstance(source_info, dict):
            source_name = source_info.get("name", "")
        date = highlight.get("date", item.get("date", ""))
        snippet = highlight.get("snippet", item.get("snippet", ""))
        link = highlight.get("link", item.get("link", ""))
        if title and source_name:
            articles.append((title, source_name, date, snippet, link))

    if not articles:
        articles = []
        for item in results[:20]:
            stories = item.get("stories", [])
            if stories:
                for s in stories[:3]:
                    src = s.get("source", {}).get("name", "") if isinstance(s.get("source"), dict) else ""
                    articles.append((s.get("title", ""), src, s.get("date", ""), s.get("snippet", ""), s.get("link", "")))
            else:
                src = item.get("source", {}).get("name", "") if isinstance(item.get("source"), dict) else ""
                articles.append((item.get("title", ""), src, item.get("date", ""), item.get("snippet", ""), item.get("link", "")))

    lines.append(f"## Articles Found: {len(articles)}")
    lines.append("")

    # Source breakdown
    sources: dict[str, int] = {}
    for _, src, _, _, _ in articles:
        sources[src] = sources.get(src, 0) + 1

    indian_fin = sum(v for k, v in sources.items() if k in _INDIAN_FINANCE_SOURCES)
    lines.append(f"  Indian financial sources: {indian_fin}/{len(articles)}")
    lines.append("")

    # Top articles with sentiment hint
    lines.append("## Recent Headlines")
    lines.append("")
    for i, (title, src, date, snippet, _link) in enumerate(articles[:15], 1):
        hint = _sentiment_hint_from_title(title)
        lines.append(f"  {i}. {hint} **{src}** — {title}")
        if date:
            lines.append(f"     _Published: {date}_")
        if snippet:
            # Truncate snippet
            snip = snippet[:200]
            if len(snippet) > 200:
                snip += "..."
            lines.append(f"     > {snip}")
        lines.append("")

    # Sentiment summary
    bullish = sum(1 for t, *_ in articles if _sentiment_hint_from_title(t) == "[BULLISH]")
    bearish = sum(1 for t, *_ in articles if _sentiment_hint_from_title(t) == "[BEARISH]")
    neutral = len(articles) - bullish - bearish
    lines.append("## Sentiment Summary (Heuristic)")
    lines.append(f"  Bullish: {bullish}  |  Bearish: {bearish}  |  Neutral: {neutral}")
    lines.append("")

    return "\n".join(lines)
