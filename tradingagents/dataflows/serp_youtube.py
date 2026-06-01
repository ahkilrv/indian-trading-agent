"""SerpAPI YouTube Search client — video sentiment for the Social Analyst.

Provides `get_youtube_sentiment_data()` which searches YouTube for stock
analysis videos and returns view counts, channel names, and publish dates
as a proxy for retail investor attention.

Requires: SERPAPI_KEY in environment (already in .env).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search"


def _ticker_to_phrase(ticker: str) -> str:
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")
    return f"{bare} stock analysis"


def _parse_views(views_str: str) -> int:
    """Parse YouTube view strings like '1.2M views', '345K views', '1200 views'."""
    s = views_str.lower().replace("views", "").strip()
    multiplier = 1
    if "m" in s:
        multiplier = 1_000_000
        s = s.replace("m", "")
    elif "k" in s:
        multiplier = 1_000
        s = s.replace("k", "")
    try:
        return int(float(s) * multiplier)
    except ValueError:
        return 0


def get_youtube_sentiment_data(ticker: str, max_results: int = 10) -> str:
    """Search YouTube for stock analysis videos via SerpAPI.

    Returns a formatted report with video titles, views, channels,
    and a summary of total retail attention (aggregate views).
    """
    phrase = _ticker_to_phrase(ticker)
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")
    api_key = os.environ.get("SERPAPI_KEY")

    lines = [
        f"# YouTube Sentiment: {phrase}",
        f"# Ticker: {bare}  |  Source: SerpAPI YouTube Search  |  Region: India",
        "",
    ]

    if not api_key:
        lines.append("## YouTube data not available (no SERPAPI_KEY)")
        return "\n".join(lines)

    try:
        resp = requests.get(
            SERPAPI_BASE,
            params={
                "engine": "youtube",
                "search_query": f"{phrase}",
                "gl": "in",
                "hl": "en",
                "api_key": api_key,
            },
            timeout=15,
        )
        data = resp.json()
        if "error" in data:
            logger.warning("SerpAPI YouTube error: %s", data["error"])
            lines.append(f"## YouTube error: {data['error']}")
            return "\n".join(lines)
    except Exception as exc:
        logger.warning("SerpAPI YouTube failed: %s", exc)
        lines.append("## YouTube data not available (SerpAPI)")
        return "\n".join(lines)

    video_results = data.get("video_results", [])

    # Also check for "movie_results" which YouTube sometimes returns
    if not video_results:
        video_results = data.get("movie_results", [])

    if not video_results:
        lines.append("  No YouTube videos found for this ticker.")
        return "\n".join(lines)

    # Parse videos
    videos = []
    for v in video_results[:max_results]:
        title = v.get("title", "")
        channel = v.get("channel", {}).get("name", "") if isinstance(v.get("channel"), dict) else ""
        views_raw = v.get("views", "")
        views = _parse_views(str(views_raw)) if views_raw else 0
        published = v.get("published_date", "")
        length = v.get("length", "")
        description = (v.get("description", "") or "")[:120]

        videos.append({
            "title": title,
            "channel": channel,
            "views": views,
            "views_display": f"{views:,}" if views else views_raw,
            "published": published,
            "length": length,
            "description": description,
        })

    total_views = sum(v["views"] for v in videos)
    total_count = len(videos)

    lines.append(f"## Videos Found: {total_count}")
    lines.append(f"  Total views (last {max_results} results): {total_views:,}")
    lines.append("")

    # Engagement level
    if total_views > 500_000:
        engagement = "VERY HIGH"
    elif total_views > 100_000:
        engagement = "HIGH"
    elif total_views > 10_000:
        engagement = "MODERATE"
    else:
        engagement = "LOW"

    lines.append(f"  Engagement level: **{engagement}**")
    lines.append("")

    lines.append("## Recent Videos")
    lines.append("")
    for v in videos:
        lines.append(f"  - **{v['channel']}** → \"{v['title']}\"")
        lines.append(f"    Views: {v['views_display']}  |  Published: {v['published']}  |  Duration: {v['length']}")
        if v["description"]:
            lines.append(f"    > {v['description']}")
        lines.append("")

    # Summary metrics for the LLM
    avg_views = total_views // max(total_count, 1)
    recent_48h = [v for v in videos if any(w in (v.get("published", "") or "").lower() for w in ("hour", "minute", "second"))]
    fresh_high_views = any(v["views"] > avg_views * 1.5 for v in recent_48h) if recent_48h else False

    lines.append("## Summary Metrics")
    lines.append(f"  Average views per video: {avg_views:,}")
    lines.append(f"  Fresh uploads (last 48h): {len(recent_48h)}")
    lines.append(f"  Recent engagement spike: {'YES' if fresh_high_views else 'No'}")
    lines.append("")

    return "\n".join(lines)
