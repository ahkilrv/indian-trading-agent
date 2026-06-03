import importlib
import logging

logger = logging.getLogger(__name__)

# Maps module_path -> list of (func_name, alias) to lazy-import on first use.
_LAZY_IMPORTS: dict[str, list[tuple[str, str]]] = {
    "tradingagents.dataflows.y_finance": [
        ("get_YFin_data_online", "get_YFin_data_online"),
        ("get_stock_stats_indicators_window", "get_stock_stats_indicators_window"),
        ("get_fundamentals", "get_yfinance_fundamentals"),
        ("get_balance_sheet", "get_yfinance_balance_sheet"),
        ("get_cashflow", "get_yfinance_cashflow"),
        ("get_income_statement", "get_yfinance_income_statement"),
        ("get_insider_transactions", "get_yfinance_insider_transactions"),
    ],
    "tradingagents.dataflows.yfinance_news": [
        ("get_news_yfinance", "get_news_yfinance"),
        ("get_global_news_yfinance", "get_global_news_yfinance"),
    ],
    "tradingagents.dataflows.alpha_vantage": [
        ("get_stock", "get_alpha_vantage_stock"),
        ("get_indicator", "get_alpha_vantage_indicator"),
        ("get_fundamentals", "get_alpha_vantage_fundamentals"),
        ("get_balance_sheet", "get_alpha_vantage_balance_sheet"),
        ("get_cashflow", "get_alpha_vantage_cashflow"),
        ("get_income_statement", "get_alpha_vantage_income_statement"),
        ("get_insider_transactions", "get_alpha_vantage_insider_transactions"),
        ("get_news", "get_alpha_vantage_news"),
        ("get_global_news", "get_alpha_vantage_global_news"),
    ],
    "tradingagents.dataflows.alpha_vantage_common": [
        ("AlphaVantageRateLimitError", "AlphaVantageRateLimitError"),
    ],
    "tradingagents.dataflows.nse_data": [
        ("get_fii_dii_activity", "get_fii_dii_activity"),
        ("get_bulk_block_deals", "get_bulk_block_deals"),
        ("get_delivery_percentage", "get_delivery_percentage"),
        ("get_nse_stock_data", "get_nse_stock_data"),
        ("get_nse_indicators", "get_nse_indicators"),
        ("get_nse_http_stock_data", "get_nse_http_stock_data"),
        ("get_nse_http_indicators", "get_nse_http_indicators"),
    ],
    "tradingagents.dataflows.dhan_data": [
        ("get_dhan_stock_data", "get_dhan_stock_data"),
        ("get_dhan_indicators", "get_dhan_indicators"),
    ],
    "tradingagents.dataflows.fyers_data": [
        ("get_fyers_stock_data", "get_fyers_stock_data"),
        ("get_fyers_indicators", "get_fyers_indicators"),
    ],
    "tradingagents.dataflows.pytrends_data": [
        ("get_trends_data", "get_trends_data"),
    ],
    "tradingagents.dataflows.rss_news": [
        ("get_rss_ticker_news", "get_rss_ticker_news"),
    ],
    "tradingagents.dataflows.serp_news": [
        ("get_serp_news_data", "get_serp_news_data"),
    ],
    "tradingagents.dataflows.serp_youtube": [
        ("get_youtube_sentiment_data", "get_youtube_sentiment_data"),
    ],
    "tradingagents.dataflows.serp_finance": [
        ("get_google_finance_data", "get_google_finance_data"),
    ],
    "tradingagents.dataflows.serp_forums": [
        ("get_forums_sentiment_data", "get_forums_sentiment_data"),
    ],
    "tradingagents.dataflows.screener_fundamentals": [
        ("get_screener_fundamentals", "get_screener_fundamentals"),
    ],
}

# Translation table: alias -> (module_path, func_name) for lazy resolution
_FUNC_MAP: dict[str, tuple[str, str]] = {}
for mod_path, funcs in _LAZY_IMPORTS.items():
    for func_name, alias in funcs:
        _FUNC_MAP[alias] = (mod_path, func_name)

# Cache for imported modules (lazy, sticky per process)
_MODULE_CACHE: dict[str, object] = {}


def _lazy_import(alias: str):
    """Import and return a callable by alias, caching the module."""
    if alias in _MODULE_CACHE:
        return _MODULE_CACHE[alias]
    mod_path, func_name = _FUNC_MAP[alias]
    mod = importlib.import_module(mod_path)
    _MODULE_CACHE[alias] = getattr(mod, func_name)
    return _MODULE_CACHE[alias]


def _get_vendor_func(method: str, vendor: str):
    """Get the vendor implementation function, importing lazily."""
    key = f"{method}:{vendor}"
    if key in _MODULE_CACHE:
        return _MODULE_CACHE[key]
    vendor_map = _VENDOR_REF_MAP.get(method, {})
    if vendor not in vendor_map:
        raise KeyError(f"Vendor '{vendor}' not found for method '{method}'")
    alias = vendor_map[vendor]
    func = _lazy_import(alias)
    _MODULE_CACHE[key] = func
    return func


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

# Mapping of methods to their vendor-specific implementation aliases (strings).
# Function references are resolved lazily on first use via _get_vendor_func().
_VENDOR_REF_MAP: dict[str, dict[str, str]] = {
    "get_stock_data": {
        "alpha_vantage": "get_alpha_vantage_stock",
        "yfinance": "get_YFin_data_online",
        "fyers": "get_fyers_stock_data",
        "nse": "get_nse_stock_data",
        "nse_http": "get_nse_http_stock_data",
        "dhan": "get_dhan_stock_data",
    },
    "get_indicators": {
        "alpha_vantage": "get_alpha_vantage_indicator",
        "yfinance": "get_stock_stats_indicators_window",
        "fyers": "get_fyers_indicators",
        "nse": "get_nse_indicators",
        "nse_http": "get_nse_http_indicators",
        "dhan": "get_dhan_indicators",
    },
    "get_fundamentals": {
        "screener": "get_screener_fundamentals",
        "alpha_vantage": "get_alpha_vantage_fundamentals",
        "yfinance": "get_yfinance_fundamentals",
    },
    "get_balance_sheet": {
        "alpha_vantage": "get_alpha_vantage_balance_sheet",
        "yfinance": "get_yfinance_balance_sheet",
    },
    "get_cashflow": {
        "alpha_vantage": "get_alpha_vantage_cashflow",
        "yfinance": "get_yfinance_cashflow",
    },
    "get_income_statement": {
        "alpha_vantage": "get_alpha_vantage_income_statement",
        "yfinance": "get_yfinance_income_statement",
    },
    "get_news": {
        "alpha_vantage": "get_alpha_vantage_news",
        "yfinance": "get_news_yfinance",
    },
    "get_global_news": {
        "yfinance": "get_global_news_yfinance",
        "alpha_vantage": "get_alpha_vantage_global_news",
    },
    "get_insider_transactions": {
        "alpha_vantage": "get_alpha_vantage_insider_transactions",
        "yfinance": "get_yfinance_insider_transactions",
    },
    "get_fii_dii_activity": {
        "nse": "get_fii_dii_activity",
    },
    "get_bulk_block_deals": {
        "nse": "get_bulk_block_deals",
    },
    "get_delivery_percentage": {
        "nse": "get_delivery_percentage",
    },
    "get_trends": {
        "pytrends": "get_trends_data",
    },
    "get_ticker_news": {
        "rss": "get_rss_ticker_news",
    },
    "get_serp_news": {
        "serpapi": "get_serp_news_data",
    },
    "get_youtube_sentiment": {
        "serpapi": "get_youtube_sentiment_data",
    },
    "get_google_finance": {
        "serpapi": "get_google_finance_data",
    },
    "get_forums_sentiment": {
        "serpapi": "get_forums_sentiment_data",
    },
}

# Backward-compatible VENDOR_METHODS — keeps the same structure but vendor values
# are list-of-vendor-strings instead of function references.
# Backward-compatible: vendor -> alias string lookup for each method.
# VENDOR_METHODS[method][vendor] returns the alias string (e.g. "get_dhan_stock_data").
# Keys (vendor names) are also accessible for iteration.
VENDOR_METHODS: dict[str, dict[str, str]] = {
    method: dict(vendors)
    for method, vendors in _VENDOR_REF_MAP.items()
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
    """Route method calls to appropriate vendor implementation with fallback support.

    Vendor modules are lazy-imported on first use to reduce memory at startup.
    """
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

        try:
            impl_func = _get_vendor_func(method, vendor)
            return impl_func(*args, **kwargs)
        except Exception as exc:
            exc_name = type(exc).__name__
            if exc_name == "AlphaVantageRateLimitError" or "RateLimit" in exc_name:
                continue
            logger.warning(
                "Vendor '%s' failed for '%s': %s. Falling through to next vendor.",
                vendor,
                method,
                exc,
            )
            continue

    raise RuntimeError(f"No available vendor for '{method}'")