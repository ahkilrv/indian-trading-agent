"""SerpAPI Google News LangChain @tool for the News Analyst."""

from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_serp_news(
    symbol: Annotated[str, "ticker symbol of the company (e.g. RELIANCE.NS)"],
    days_back: Annotated[int, "how many days back to search"] = 7,
) -> str:
    """Fetch structured Google News articles via SerpAPI for a stock ticker.

    Returns headlines, source, date, snippet, and a heuristic sentiment
    breakdown (bullish/bearish/neutral).  More reliable than RSS scraping.

    Args:
        symbol: Ticker symbol (e.g. RELIANCE.NS, TCS.NS)
        days_back: Lookback window in days (default 7)

    Returns:
        Formatted markdown report with article count, sources, and sentiment.
    """
    return route_to_vendor("get_serp_news", symbol, days_back)
