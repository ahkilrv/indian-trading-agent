"""FastAPI application for the Indian Market Trading Agent."""

import json
import math
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), override=True)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from backend.db import ensure_db
from backend.routers import market_data, analysis, watchlist, backtest, strategies, scanner, performance, recommender, settings as settings_router, news as news_router, simulation as simulation_router, insights as insights_router, fii_dii as fii_dii_router, calendar as calendar_router, concentration as concentration_router, daily_verdict as daily_verdict_router, signal_performance as signal_performance_router, verdict_calibration as verdict_calibration_router, regime as regime_router, confidence_calibration as confidence_calibration_router, shadow_trades as shadow_trades_router, memory as memory_router
from backend.settings_manager import load_api_keys_into_env, apply_llm_config_to_default


def _sanitize_nan(obj):
    """Recursively replace NaN/Infinity floats with None (JSON-safe)."""
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_nan(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
    return obj


# Custom JSONResponse that auto-sanitizes NaN values before serialization
class SafeJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(
            _sanitize_nan(content),
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_db()
    load_api_keys_into_env()
    apply_llm_config_to_default()
    yield


app = FastAPI(
    title="Indian Market Trading Agent",
    description="AI-powered short-term trading decisions for NSE/BSE",
    version="0.1.0",
    lifespan=lifespan,
    default_response_class=SafeJSONResponse,  # auto-sanitize NaN in all responses
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001",
        ).split(",")
        if o.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── CORS helper for Vercel preview domains ─────────────────────────
# Starlette 1.x removed allow_origin_regex, so we add a small middleware
# that permits any *.vercel.app origin on top of the static list above.
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class _VercelCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "")
        is_vercel = origin and ".vercel.app" in origin
        is_local = origin and ("localhost" in origin or "127.0.0.1" in origin)

        if is_vercel or is_local:
            # Handle OPTIONS preflight before CORSMiddleware gets it
            if request.method == "OPTIONS":
                headers = {
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Methods": "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization",
                    "Access-Control-Max-Age": "600",
                }
                return Response(status_code=200, headers=headers)

            response: Response = await call_next(request)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            return response

        return await call_next(request)

app.add_middleware(_VercelCORSMiddleware)

app.include_router(market_data.router)
app.include_router(analysis.router)
app.include_router(watchlist.router)
app.include_router(backtest.router)
app.include_router(strategies.router)
app.include_router(scanner.router)
app.include_router(performance.router)
app.include_router(recommender.router)
app.include_router(settings_router.router)
app.include_router(news_router.router)
app.include_router(simulation_router.router)
app.include_router(insights_router.router)
app.include_router(fii_dii_router.router)
app.include_router(calendar_router.router)
app.include_router(concentration_router.router)
app.include_router(daily_verdict_router.router)
app.include_router(signal_performance_router.router)
app.include_router(verdict_calibration_router.router)
app.include_router(regime_router.router)
app.include_router(confidence_calibration_router.router)
app.include_router(shadow_trades_router.router)
app.include_router(memory_router.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "indian-trading-agent"}


@app.get("/api/config")
def get_config():
    from tradingagents.default_config import DEFAULT_CONFIG
    safe_keys = [
        "llm_provider", "deep_think_llm", "quick_think_llm",
        "market", "default_exchange", "trading_style",
        "max_debate_rounds", "max_risk_discuss_rounds",
        "dry_run", "order_execution_enabled",
        "max_position_value", "max_loss_per_trade", "max_daily_loss",
        "max_open_positions",
    ]
    return {k: DEFAULT_CONFIG.get(k) for k in safe_keys}
