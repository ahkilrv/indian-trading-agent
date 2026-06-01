"""RSS news tools for LangGraph agents.

Provides `get_ticker_news` (Google News RSS + ET RSS) as a LangChain @tool.
"""

from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_ticker_news(
    symbol: Annotated[str, "ticker symbol of the company (e.g. RELIANCE.NS)"],
    days_back: Annotated[int, "how many days back to search"] = 7,
) -> str:
    """Fetch ticker-specific news from Google News RSS and Economic Times RSS.
    
    Searches Indian financial news feeds for articles mentioning the ticker.
    Sources: Google News India, Economic Times (Markets, IPO, Industry, Economy, Corporate).
    
    Args:
        symbol: Ticker symbol of the company (e.g. RELIANCE.NS, TCS)
        days_back: How many days back to look for news (default 7)
    
    Returns:
        Formatted markdown report with news articles grouped by source.
    """
    return route_to_vendor("get_ticker_news", symbol, days_back)
