"""SerpAPI Google Finance LangChain @tool for Market/Fundamentals Analyst."""

from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_google_finance(
    symbol: Annotated[str, "ticker symbol of the company (e.g. RELIANCE.NS)"],
    window: Annotated[str, "time window: 1D, 5D, 1M, 6M, 1Y, 5Y, MAX"] = "1M",
) -> str:
    """Fetch stock data from Google Finance via SerpAPI.

    Provides real-time price, price change, key statistics (PE, market cap,
    dividend yield), financial statements (income, balance sheet, cash flow),
    and intraday OHLCV graph data.  Acts as a secondary verification source
    alongside yfinance and NSE sidecar data.

    Args:
        symbol: Ticker symbol (e.g. RELIANCE.NS, TCS.NS)
        window: Chart time window — 1D, 5D, 1M, 6M, 1Y, 5Y, MAX

    Returns:
        Formatted markdown report with price, stats, and financials.
    """
    return route_to_vendor("get_google_finance", symbol, window)
