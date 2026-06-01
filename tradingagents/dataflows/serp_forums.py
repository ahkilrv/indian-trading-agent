"""SerpAPI Google Forums client — forum sentiment for Social Analyst.

Provides `get_forums_sentiment_data()` which searches Google's "Forums" tab
for Reddit, Quora, and other forum discussions about a stock ticker.
Returns thread titles, comment counts, top answers, and vote counts
as structured social sentiment signals.

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
    return f"{bare} stock"


def get_forums_sentiment_data(ticker: str, days_back: int = 30) -> str:
    """Search Google Forums tab for stock discussions via SerpAPI.

    Returns a formatted report with Reddit/forum threads, comment counts,
    top answers with votes, and a social sentiment summary.
    """
    phrase = _ticker_to_phrase(ticker)
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")
    api_key = os.environ.get("SERPAPI_KEY")

    lines = [
        f"# Google Forums Sentiment: {phrase}",
        f"# Ticker: {bare}  |  Source: SerpAPI Google Forums  |  Region: India",
        "",
    ]

    if not api_key:
        lines.append("## Forums data not available (no SERPAPI_KEY)")
        return "\n".join(lines)

    try:
        resp = requests.get(
            SERPAPI_BASE,
            params={
                "engine": "google_forums",
                "q": f"{phrase} NSE India",
                "gl": "in",
                "hl": "en",
                "api_key": api_key,
            },
            timeout=15,
        )
        data = resp.json()
        if "error" in data:
            # Fallback: search without "India" qualifier
            resp2 = requests.get(
                SERPAPI_BASE,
                params={
                    "engine": "google_forums",
                    "q": phrase,
                    "gl": "in",
                    "hl": "en",
                    "api_key": api_key,
                },
                timeout=15,
            )
            data2 = resp2.json()
            if "error" in data2:
                logger.warning("SerpAPI Forums error: %s", data2["error"])
                lines.append(f"## Forums error: {data2['error']}")
                return "\n".join(lines)
            data = data2
    except Exception as exc:
        logger.warning("SerpAPI Forums failed: %s", exc)
        lines.append("## Forums data not available (SerpAPI)")
        return "\n".join(lines)

    results = data.get("organic_results", [])
    if not results:
        lines.append("  No forum discussions found for this ticker.")
        return "\n".join(lines)

    lines.append(f"## Discussions Found: {len(results)}")
    lines.append("")

    # Track sentiment across threads
    total_comments = 0
    total_votes = 0
    reddit_count = 0
    sources: dict[str, int] = {}
    threads: list[dict] = []

    for item in results:
        source = item.get("source", "")
        title = item.get("title", "")
        snippet = item.get("snippet", "")[:200]
        link = item.get("link", "")
        date = item.get("date", "")
        meta = item.get("displayed_meta", "")

        sources[source] = sources.get(source, 0) + 1
        if "reddit" in source.lower():
            reddit_count += 1

        thread = {"title": title, "source": source, "snippet": snippet, "date": date, "meta": meta}

        # Parse answers (top comments)
        answers = item.get("answers", [])
        ans_strs = []
        for a in answers[:3]:
            ans_text = (a.get("answer", "") or "")[:120]
            votes = a.get("votes", 0)
            total_votes += votes
            is_top = a.get("top_answer", False)
            prefix = "⭐ TOP" if is_top else "  ·"
            ans_strs.append(f"     {prefix} [+{votes}] {ans_text}")
        thread["answers"] = ans_strs

        # Parse comment counts
        if "comments" in meta.lower() or "answers" in meta.lower():
            try:
                count_str = meta.split("·")[0].strip().replace("comments", "").replace("comment", "").replace("answers", "").replace("answer", "").replace("K+", "000").replace("K", "000").replace("+", "").strip()
                total_comments += int(count_str.replace(".", "").split()[0])
            except (ValueError, IndexError):
                pass

        threads.append(thread)

    # Engagement stats
    lines.append("## Engagement Summary")
    lines.append(f"  Total threads: {len(results)}")
    lines.append(f"  From Reddit: {reddit_count}/{len(results)}")
    lines.append(f"  Estimated comments: {total_comments if total_comments else 'N/A'}")
    lines.append(f"  Total answer votes: {total_votes}")
    lines.append("")

    # Source breakdown
    lines.append("## Source Breakdown")
    for src, count in sorted(sources.items(), key=lambda x: -x[1]):
        lines.append(f"  {src}: {count} threads")
    lines.append("")

    # Thread details
    lines.append("## Top Discussions")
    lines.append("")
    for i, t in enumerate(threads[:10], 1):
        lines.append(f"  {i}. **{t['source']}** — {t['title']}")
        if t["meta"]:
            lines.append(f"     {t['meta']}")
        if t["date"]:
            lines.append(f"     Published: {t['date']}")
        if t["snippet"]:
            lines.append(f"     > {t['snippet']}")
        for ans in t["answers"]:
            lines.append(ans)
        lines.append("")

    # Sentiment assessment
    lines.append("## Social Sentiment Signal")
    if reddit_count > 5:
        lines.append(f"  **High forum activity** — {reddit_count} Reddit threads indicate strong retail attention")
    elif reddit_count > 2:
        lines.append(f"  **Moderate forum activity** — {reddit_count} Reddit threads, moderate retail interest")
    else:
        lines.append(f"  **Low forum activity** — limited retail discussion")

    if total_votes > 100:
        lines.append(f"  High vote count ({total_votes}) signals active community engagement")
    lines.append("")

    return "\n".join(lines)
