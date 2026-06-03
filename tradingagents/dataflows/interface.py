from typing import Annotated

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError

# Import Indian market data functions
from .nse_data import (
    get_fii_dii_activity,
    get_bulk_block_deals,
    get_delivery_percentage,
    get_nse_stock_data,
    get_nse_indicators,
    get_nse_http_stock_data,
    get_nse_http_indicators,
)

# Import Dhan broker API
from .dhan_data import get_dhan_stock_data, get_dhan_indicators

# Import Fyers API data functions
from .fyers_data import get_fyers_stock_data, get_fyers_indicators

# Import social sentiment and RSS news data functions
from .pytrends_data import get_trends_data
from .rss_news import get_rss_ticker_news

# Import SerpAPI data functions
from .serp_news import get_serp_news_data
from .serp_youtube import get_youtube_sentiment_data
from .serp_finance import get_google_finance_data
from .serp_forums import get_forums_sentiment_data

# Import Screener.in fundamentals
from .screener_fundamentals import get_screener_fundamentals

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    },
    "indian_market_data": {
        "description": "NSE/BSE specific data (FII/DII, bulk deals, delivery %)",
        "tools": [
            "get_fii_dii_activity",
            "get_bulk_block_deals",
            "get_delivery_percentage",
        ]
    },
    "social_sentiment_data": {
        "description": "Social media and search trend analytics",
        "tools": [
            "get_trends",
        ]
    },
    "ticker_news_rss": {
        "description": "Ticker-specific RSS news feeds",
        "tools": [
            "get_ticker_news",
        ]
    },
    "serp_news_data": {
        "description": "SerpAPI Google News structured data",
        "tools": [
            "get_serp_news",
        ]
    },
    "serp_social_data": {
        "description": "SerpAPI YouTube and Forums social data",
        "tools": [
            "get_youtube_sentiment",
            "get_forums_sentiment",
        ]
    },
    "serp_finance_data": {
        "description": "SerpAPI Google Finance stock data",
        "tools": [
            "get_google_finance",
        ]
    },
}


VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "nse",
    "fyers",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "fyers": get_fyers_stock_data,
        "nse": get_nse_stock_data,
        "nse_http": get_nse_http_stock_data,
        "dhan": get_dhan_stock_data,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "fyers": get_fyers_indicators,
        "nse": get_nse_indicators,
        "nse_http": get_nse_http_indicators,
        "dhan": get_dhan_indicators,
    },
    # fundamental_data
    "get_fundamentals": {
        "screener": get_screener_fundamentals,
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
    # Indian market data (NSE-specific, no vendor fallback needed)
    "get_fii_dii_activity": {
        "nse": get_fii_dii_activity,
    },
    "get_bulk_block_deals": {
        "nse": get_bulk_block_deals,
    },
    "get_delivery_percentage": {
        "nse": get_delivery_percentage,
    },
    # Social sentiment
    "get_trends": {
        "pytrends": get_trends_data,
    },
    # Ticker-specific RSS news
    "get_ticker_news": {
        "rss": get_rss_ticker_news,
    },
    # SerpAPI integrations
    "get_serp_news": {
        "serpapi": get_serp_news_data,
    },
    "get_youtube_sentiment": {
        "serpapi": get_youtube_sentiment_data,
    },
    "get_google_finance": {
        "serpapi": get_google_finance_data,
    },
    "get_forums_sentiment": {
        "serpapi": get_forums_sentiment_data,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")


def get_data_source_label(method: str) -> str:
    """Return a human-readable label for the configured data vendor.

    Used by the frontend to display the active data source (e.g. "Yahoo Finance",
    "NSE India", "Fyers") in the UI.
    """
    category = get_category_for_method(method)
    vendor_raw = get_vendor(category, method)
    primary = vendor_raw.split(",")[0].strip().lower()

    # Fallback: if config didn't specify a vendor, infer from VENDOR_METHODS
    if primary == "default" and method in VENDOR_METHODS:
        vendors = list(VENDOR_METHODS[method].keys())
        primary = vendors[0] if vendors else primary

    label_map: dict[str, str] = {
        "yfinance": "Yahoo Finance",
        "nse": "NSE India",
        "nse_http": "NSE India",
        "dhan": "DhanHQ",
        "fyers": "Fyers",
        "alpha_vantage": "Alpha Vantage",
        "pytrends": "Google Trends",
        "rss": "RSS Feeds",
        "serpapi": "SerpAPI",
    }
    return label_map.get(primary, primary.title())


def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            return impl_func(*args, **kwargs)
        except AlphaVantageRateLimitError:
            continue  # Only rate limits trigger fallback
        except Exception as exc:
            # Graceful fallback for NSE (Akamai blocks) and other transient issues.
            # Log the failure and try the next vendor in the chain.
            import logging
            logging.getLogger(__name__).warning(
                "Vendor '%s' failed for '%s': %s. Falling through to next vendor.",
                vendor,
                method,
                exc,
            )
            continue

    raise RuntimeError(f"No available vendor for '{method}'")