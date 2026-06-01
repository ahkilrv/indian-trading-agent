"""SerpAPI Google Forums LangChain @tool for the Social Media Analyst."""

from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_forums_sentiment(
    symbol: Annotated[str, "ticker symbol of the company (e.g. RELIANCE.NS)"],
    days_back: Annotated[int, "how many days back to search"] = 30,
) -> str:
    """Search Google Forums tab for stock discussions via SerpAPI.

    Returns Reddit, Quora, and other forum threads about the stock.
    Includes: thread titles, comment counts, top answers with vote counts,
    and a social sentiment signal (high/moderate/low retail attention).

    This is a Reddit sentiment proxy — no asyncpraw app credentials needed.

    Args:
        symbol: Ticker symbol (e.g. RELIANCE.NS, TCS.NS)
        days_back: Lookback window in days (default 30)

    Returns:
        Formatted markdown report with forum threads and sentiment summary.
    """
    return route_to_vendor("get_forums_sentiment", symbol, days_back)
