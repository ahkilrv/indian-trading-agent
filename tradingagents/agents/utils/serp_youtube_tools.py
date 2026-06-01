"""SerpAPI YouTube Search LangChain @tool for the Social Media Analyst."""

from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_youtube_sentiment(
    symbol: Annotated[str, "ticker symbol of the company (e.g. RELIANCE.NS)"],
    max_results: Annotated[int, "max videos to return"] = 10,
) -> str:
    """Search YouTube for stock analysis videos via SerpAPI.

    Returns video titles, view counts, channel names, and publish dates.
    Used as a proxy for retail investor attention — high view counts
    indicate strong social engagement with the stock.

    Args:
        symbol: Ticker symbol (e.g. RELIANCE.NS, TCS.NS)
        max_results: Maximum number of video results (default 10)

    Returns:
        Formatted markdown report with video details and engagement summary.
    """
    return route_to_vendor("get_youtube_sentiment", symbol, max_results)
