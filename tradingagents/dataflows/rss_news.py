"""RSS-based news provider for the News Analyst.

Fetches Indian financial news from:
- Google News RSS (ticker-specific, region India, English)
- Economic Times Markets RSS (pre-configured in backend/news_sources.py)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# ── RSS feed URLs ───────────────────────────────────────────────────

_GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)

_ET_RSS_FEEDS = {
    "markets": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "ipo": "https://economictimes.indiatimes.com/markets/ipos/fpos/rssfeeds/62256163.cms",
    "industry": "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms",
    "economy": "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
    "corporate": "https://economictimes.indiatimes.com/news/company/corporate-trends/rssfeeds/2146843.cms",
}


def _parse_rss_feed(url: str, timeout: int = 10) -> list[dict]:
    """Parse an RSS feed URL and return a list of article dicts."""
    try:
        import feedparser  # optional, installed separately
    except ImportError:
        logger.warning("feedparser not installed — RSS news unavailable")
        return []

    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        logger.warning("RSS feed parse failed for %s: %s", url, exc)
        return []

    articles: list[dict] = []
    for entry in feed.entries[:15]:
        articles.append(
            {
                "title": getattr(entry, "title", ""),
                "summary": (getattr(entry, "summary", "") or "")[:400],
                "url": getattr(entry, "link", ""),
                "published": getattr(entry, "published", ""),
                "source": getattr(feed.feed, "title", url),
            }
        )
    return articles


def _filter_by_ticker(articles: list[dict], ticker: str) -> list[dict]:
    """Keep only articles whose title or summary mentions the ticker."""
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")
    company = {
        "RELIANCE": "Reliance",
        "TCS": "TCS|Tata Consultancy",
        "INFY": "Infosys",
        "HDFCBANK": "HDFC Bank",
        "ICICIBANK": "ICICI Bank",
        "TECHM": "Tech Mahindra",
        "WIPRO": "Wipro",
        "SBIN": "SBI|State Bank of India",
        "ITC": "ITC(?!.*ITC )",
        "BHARTIARTL": "Bharti Airtel",
        "TATAMOTORS": "Tata Motors",
        "TATASTEEL": "Tata Steel",
    }
    pattern = company.get(bare, bare)

    filtered: list[dict] = []
    for a in articles:
        text = f"{a['title']} {a['summary']}"
        if re.search(pattern, text, re.IGNORECASE):
            filtered.append(a)
    return filtered


def get_rss_ticker_news(
    ticker: str,
    days_back: int = 7,
) -> str:
    """Fetch ticker-specific news from Google News RSS + Economic Times RSS.

    Returns a formatted markdown report string for the News Analyst LLM.
    """
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")

    lines: list[str] = [
        f"# RSS News for {bare}",
        f"# Sources: Google News India, Economic Times",
        f"# Fetched: {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}",
        "",
    ]

    all_articles: list[dict] = []

    # --- Google News RSS ---
    query = f"{bare} stock NSE"
    url = _GOOGLE_NEWS_RSS.format(query=query.replace(" ", "+"))
    logger.info("Fetching Google News RSS for %s: %s", bare, url)
    gn_articles = _parse_rss_feed(url)
    gn_filtered = _filter_by_ticker(gn_articles, ticker)
    all_articles.extend(gn_filtered)
    lines.append(f"## Google News India")
    if gn_filtered:
        for a in gn_filtered[:5]:
            lines.append(f"- **{a['title']}**")
            if a["summary"]:
                lines.append(f"  {a['summary'][:200]}")
            if a["published"]:
                lines.append(f"  _{a['published']}_")
            lines.append("")
    else:
        lines.append("  No ticker-specific articles found.")
        lines.append("")

    # --- Economic Times RSS ---
    lines.append("## Economic Times")
    et_count = 0
    for feed_name, feed_url in _ET_RSS_FEEDS.items():
        try:
            et_articles = _parse_rss_feed(feed_url)
            et_filtered = _filter_by_ticker(et_articles, ticker)
            if et_filtered:
                if et_count == 0:
                    lines.append("")
                for a in et_filtered[:2]:
                    lines.append(f"- **{a['title']}**")
                    if a["published"]:
                        lines.append(f"  _{a['published']}_")
                    lines.append("")
                et_count += len(et_filtered)
        except Exception as exc:
            logger.warning("ET feed %s failed: %s", feed_name, exc)

    if et_count == 0:
        lines.append("  No ticker-specific articles found.")

    # --- Summary ---
    total = len(all_articles) + et_count
    lines.insert(2, f"# Total articles found: {total}")
    lines.insert(3, "")

    return "\n".join(lines)
