import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    # LLM settings
    "llm_provider": "deepseek",
    "deep_think_llm": "deepseek-v4-pro",
    "quick_think_llm": "deepseek-reasoner",
    # Provider-specific thinking configuration
    "google_thinking_level": None,
    "openai_reasoning_effort": None,
    "anthropic_effort": None,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    "data_vendors": {
        "core_stock_apis": "dhan,yfinance",
        "technical_indicators": "dhan,yfinance",
        "fundamental_data": "screener,yfinance",
        "news_data": "alpha_vantage,yfinance",
        "indian_market_data": "nse",
    },
    "tool_vendors": {},
    # === Indian Market Settings ===
    "market": "india",
    "default_exchange": "NSE",
    "ticker_suffix": ".NS",  # yfinance suffix for NSE (.BO for BSE)
    "market_timezone": "Asia/Kolkata",
    "market_open": "09:15",
    "market_close": "15:30",
    "currency": "INR",
    # Trading style
    "trading_style": "short_term",  # short_term | swing | positional
    "default_lookback_days": 15,
    # Indian market news queries (used by yfinance news when market=india)
    "global_news_queries": [
        "Indian stock market Sensex Nifty",
        "RBI monetary policy interest rates India",
        "India GDP inflation economic outlook",
        "FII DII activity Indian markets",
        "India rupee forex exchange rate",
    ],
    # === Kite API Settings (Phase 4) ===
    "kite_api_key": None,
    "kite_api_secret": None,
    "kite_access_token": None,
    # === Order Management Safety (Phase 4) ===
    "order_execution_enabled": False,
    "dry_run": True,
    "max_position_value": 100000,  # INR
    "max_loss_per_trade": 5000,  # INR
    "max_daily_loss": 20000,  # INR
    "max_open_positions": 5,
    "require_stop_loss": True,
    "allowed_exchanges": ["NSE"],
    "allowed_products": ["MIS", "CNC"],
}