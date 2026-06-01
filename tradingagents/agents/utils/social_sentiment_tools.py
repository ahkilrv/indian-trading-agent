"""Social sentiment tools for LangGraph agents.

Provides `get_trends` (Google Trends) as a LangChain @tool.
"""

from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_trends(
    symbol: Annotated[str, "ticker symbol of the company (e.g. RELIANCE.NS)"],
    timeframe: Annotated[str, "timeframe for Google Trends (e.g. 'today 3-m', 'today 1-m', 'today 7-d')"] = "today 3-m",
) -> str:
    """Retrieve Google Trends search interest data for a stock ticker.
    
    Shows interest-over-time (0-100 index), rising related queries,
    and whether search interest is spiking (>2x average).
    Uses the pytrends vendor configured in data_vendors.
    
    Args:
        symbol: Ticker symbol of the company (e.g. RELIANCE.NS, TCS)
        timeframe: Time window ('today 3-m', 'today 1-m', 'today 7-d')
    
    Returns:
        Formatted report string with search interest data.
    """
    return route_to_vendor("get_trends", symbol, timeframe)
