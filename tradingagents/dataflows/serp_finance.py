"""SerpAPI Google Finance client — stock data for Market/Fundamentals Analyst.

Provides `get_google_finance_data()` which queries Google Finance via SerpAPI
for real-time price, key statistics, and financial statements (income,
balance sheet, cash flow).  Acts as a secondary verification source.

Requires: SERPAPI_KEY in environment (already in .env).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search"


def _get_nse_ticker(ticker: str) -> str:
    """Convert ticker to Google Finance NSE format: RELIANCE → RELIANCE:NSE"""
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")
    return f"{bare}:NSE"


def get_google_finance_data(ticker: str, window: str = "1M") -> str:
    """Fetch stock data from Google Finance via SerpAPI.

    Args:
        ticker: NSE ticker symbol (e.g. RELIANCE.NS)
        window: Time window for the graph (1D, 5D, 1M, 6M, 1Y, 5Y, MAX)

    Returns formatted report with price, key stats, and financials.
    """
    g_ticker = _get_nse_ticker(ticker)
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")
    api_key = os.environ.get("SERPAPI_KEY")

    lines = [
        f"# Google Finance: {bare}",
        f"# Ticker: {g_ticker}  |  Window: {window}  |  Source: SerpAPI Google Finance",
        "",
    ]

    if not api_key:
        lines.append("## Google Finance data not available (no SERPAPI_KEY)")
        return "\n".join(lines)

    try:
        resp = requests.get(
            SERPAPI_BASE,
            params={
                "engine": "google_finance",
                "q": g_ticker,
                "hl": "en",
                "window": window,
                "api_key": api_key,
            },
            timeout=15,
        )
        data = resp.json()
        if "error" in data:
            logger.warning("SerpAPI Google Finance error: %s", data["error"])
            # Try without exchange suffix
            resp2 = requests.get(
                SERPAPI_BASE,
                params={
                    "engine": "google_finance",
                    "q": bare,
                    "hl": "en",
                    "window": window,
                    "api_key": api_key,
                },
                timeout=15,
            )
            data2 = resp2.json()
            if "error" in data2:
                lines.append(f"## Google Finance error: {data2['error']}")
                return "\n".join(lines)
            data = data2
    except Exception as exc:
        logger.warning("SerpAPI Google Finance failed: %s", exc)
        lines.append("## Google Finance data not available (SerpAPI)")
        return "\n".join(lines)

    # Parse summary
    summary = data.get("summary", {})
    if summary:
        price = summary.get("extracted_price", summary.get("price", "N/A"))
        currency = summary.get("currency", "")
        movement = summary.get("price_movement", {})
        change_pct = movement.get("percentage", 0)
        change_val = movement.get("value", 0)
        direction = movement.get("movement", "")

        lines.append("## Price Summary")
        lines.append(f"  Price: {price} {currency}")
        lines.append(f"  Change: {direction} {change_val:.2f} ({change_pct:.2f}%)")
        lines.append(f"  Exchange: {summary.get('exchange', 'N/A')}")
        lines.append("")

    # Parse Key Stats (from knowledge_graph)
    kg = data.get("knowledge_graph", {})
    key_stats = kg.get("key_stats", {})
    stats = key_stats.get("stats", [])
    if stats:
        lines.append("## Key Statistics")
        for s in stats:
            label = s.get("label", "")
            value = s.get("value", "")
            lines.append(f"  {label}: {value}")
        lines.append("")

    # Parse company info
    about = kg.get("about", [])
    if about:
        for section in about:
            info = section.get("info", [])
            if info:
                lines.append(f"## {section.get('title', 'Company Info')}")
                for item in info:
                    lines.append(f"  {item.get('label', '')}: {item.get('value', '')}")
                lines.append("")

    # Parse Financials
    financials = data.get("financials", [])
    if financials:
        lines.append("## Financial Statements")
        for statement in financials:
            title = statement.get("title", "")
            results = statement.get("results", [])
            if not results:
                continue

            lines.append(f"### {title}")
            for period_data in results[:2]:  # show quarterly + annual
                period = period_data.get("date", "")
                period_type = period_data.get("period_type", "")
                table = period_data.get("table", [])
                if table:
                    lines.append(f"  **{period} ({period_type})**")
                    for row in table[:8]:  # top 8 rows
                        row_title = row.get("title", "")
                        value = row.get("value", "")
                        change = row.get("change", "")
                        change_str = f" (Δ {change})" if change else ""
                        lines.append(f"    {row_title}: {value}{change_str}")
                lines.append("")
            lines.append("")

    # Parse News from Google Finance
    news = data.get("news_results", [])
    if news:
        lines.append("## Recent News (via Google Finance)")
        for item in news[:5]:
            if isinstance(item, dict):
                title = item.get("snippet", "") or item.get("title", "")
                source = item.get("source", "")
                date = item.get("date", "")
                lines.append(f"  - [{source}] {title} ({date})")
        lines.append("")

    # Parse graph data for OHLCV summary
    graph = data.get("graph", [])
    if graph:
        prices = [p.get("price", 0) for p in graph if p.get("price")]
        volumes = [p.get("volume", 0) for p in graph if p.get("volume")]
        if prices:
            lines.append("## OHLCV Summary (from intraday graph)")
            lines.append(f"  High: {max(prices):.2f}")
            lines.append(f"  Low:  {min(prices):.2f}")
            lines.append(f"  Avg:  {sum(prices)/len(prices):.2f}")
            lines.append(f"  Total Volume: {sum(volumes):,}")
            lines.append("")

    return "\n".join(lines)
