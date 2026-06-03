"""Recommendation Engine API — combines all strategies into ranked trade ideas."""

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from backend.recommender import recommend, _analyze_stock, recommend_stream

router = APIRouter(prefix="/api/recommend", tags=["recommend"])


@router.get("/")
def get_recommendations(
    universe: str = Query("nifty100", description="nifty50, nifty100, or bse250"),
    min_signals: int = Query(2, description="Min aligned signals (kept for backward compat)"),
):
    """Get ranked trade recommendations combining all strategies.

    Returns ALL stocks ranked by continuous score — no more empty results.
    The ``min_signals`` parameter is retained for API compatibility but does
    NOT filter results away — every stock appears in the ``results`` array.
    """
    return recommend(universe, min_signals)


@router.get("/stock/{ticker}")
def analyze_single_stock(ticker: str):
    """Get recommendation for a single stock."""
    result = _analyze_stock(ticker)
    if not result:
        return {"error": f"Could not analyze {ticker}"}
    return result


@router.get("/stream")
async def stream_recommendations(
    universe: str = Query("nifty100", description="nifty50, nifty100, or bse250"),
):
    """SSE-streamed recommendations. Results yield progressively as each stock completes.

    Event types:
      - ``metadata`` — market bias + calendar events
      - ``result`` — individual stock analysis (one per stock)
      - ``progress`` — ``{done, total}`` heartbeat every 5 stocks
      - ``complete`` — final sorted response with all buckets
    """
    return StreamingResponse(
        recommend_stream(universe=universe),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
