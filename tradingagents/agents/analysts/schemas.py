"""Pydantic schemas for structured LLM outputs from analyst and researcher agents.

These schemas enforce declarative JSON output so that downstream
researchers and managers can ingest clean dictionaries of scores, verdicts,
and support/resistance levels without parsing free-text narratives.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal, Optional, Type

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


RESEARCHER_SCHEMA_PROMPT = """\
You MUST output ONLY a valid JSON object with exactly these keys:
{
  "ticker": "string — the stock ticker (e.g. RELIANCE.NS)",
  "bias": "PERMABULL | SHORT_SELLER",
  "thesis_summary": "string — exactly 2 sentences, highly opinionated",
  "primary_catalyst": "string — the single most important driver for this thesis",
  "supporting_metrics": [
    {
      "metric_name": "string — what the metric measures",
      "value": "number or string — the exact value from the upstream data",
      "source": "Fundamentals | Market | News"
    }
  ],
  "target_price": "number — your price target",
  "confidence_score": "number between 0.0 and 1.0",
  "fatal_flaw_ignored": "string — the major risk you are deliberately ignoring"
}
No other text. No markdown, no explanation, no conversational filler."""


def extract_and_validate(
    raw_text: str,
    model: Type[BaseModel],
    *,
    ticker: str,
) -> Optional[dict[str, Any]]:
    """Extract a JSON object from an LLM response and validate it against *model*.

    Strategy (tried in order):
    1. Direct ``json.loads`` of the whole string.
    2. Regex extraction of the first ``{...}`` block (greedy).
    3. Regex extraction of a ```json ... ``` fenced block.

    On success returns the validated model as a plain dict.  On any failure
    logs a warning and returns ``None`` – the caller should fall back to the
    raw text report.
    """
    candidates: list[str] = []

    # Strategy 1 – direct parse
    stripped = raw_text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)

    # Strategy 2 – first balanced brace-pair
    m = re.search(r"\{.*\}", stripped, re.DOTALL)
    if m:
        block = m.group(0)
        if block not in candidates:
            candidates.append(block)

    # Strategy 3 – fenced code block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if m:
        block = m.group(1)
        if block not in candidates:
            candidates.append(block)

    for i, candidate in enumerate(candidates):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        # Ensure ticker is present, even if the LLM omitted it
        if "ticker" not in data or not data.get("ticker"):
            data["ticker"] = ticker

        try:
            validated = model.model_validate(data)
            logger.debug(
                "extract_and_validate[%s] succeeded on candidate %d",
                model.__name__,
                i,
            )
            return validated.model_dump()
        except ValidationError as exc:
            logger.warning(
                "extract_and_validate[%s] candidate %d failed validation: %s",
                model.__name__,
                i,
                exc,
            )

    logger.warning(
        "extract_and_validate[%s] could not extract valid JSON from: %.200s...",
        model.__name__,
        raw_text,
    )
    return None


def format_analysis_for_prompt(
    *,
    market_analysis: Optional[dict[str, Any]] = None,
    fundamentals_analysis: Optional[dict[str, Any]] = None,
    news_analysis: Optional[dict[str, Any]] = None,
) -> str:
    """Render structured analysis dicts as a concise text block for LLM prompts.

    Returns an empty string if no analysis dicts are provided.
    """
    blocks: list[str] = []

    if market_analysis:
        blocks.append(
            "Structured Market Analysis:\n"
            f"  Ticker: {market_analysis.get('ticker', 'N/A')}\n"
            f"  Trend: {market_analysis.get('current_trend', 'N/A')}\n"
            f"  Support: {market_analysis.get('key_support', 'N/A')}\n"
            f"  Resistance: {market_analysis.get('key_resistance', 'N/A')}\n"
            f"  Momentum: {market_analysis.get('momentum_state', 'N/A')}\n"
            f"  Institutional Flow: {market_analysis.get('institutional_flow_bias', 'N/A')}\n"
            f"  Technical Verdict: {market_analysis.get('technical_verdict', 'N/A')}"
        )

    if fundamentals_analysis:
        blocks.append(
            "Structured Fundamentals Analysis:\n"
            f"  Ticker: {fundamentals_analysis.get('ticker', 'N/A')}\n"
            f"  Valuation Score (1-10): {fundamentals_analysis.get('valuation_score', 'N/A')}\n"
            f"  Health Status: {fundamentals_analysis.get('health_status', 'N/A')}\n"
            f"  Strength: {fundamentals_analysis.get('primary_strength', 'N/A')}\n"
            f"  Weakness: {fundamentals_analysis.get('primary_weakness', 'N/A')}\n"
            f"  Fundamental Verdict: {fundamentals_analysis.get('overall_fundamental_verdict', 'N/A')}"
        )

    if news_analysis:
        blocks.append(
            "Structured News Analysis:\n"
            f"  Ticker: {news_analysis.get('ticker', 'N/A')}\n"
            f"  Sentiment Score (-1 to +1): {news_analysis.get('sentiment_score', 'N/A')}\n"
            f"  Catalyst Identified: {news_analysis.get('catalyst_identified', 'N/A')}\n"
            f"  Primary Driver: {news_analysis.get('primary_driver', 'N/A')}\n"
            f"  Driver Source Quote: {news_analysis.get('driver_source', 'N/A')}\n"
            f"  News Verdict: {news_analysis.get('news_verdict', 'N/A')}"
        )

    return "\n\n".join(blocks)


# ── Researcher Schemas ────────────────────────────────────────────


class MetricCitation(BaseModel):
    """A specific upstream data point that supports the researcher's thesis."""

    metric_name: str
    value: str | float
    source: Literal["Fundamentals", "Market", "News"]


class ResearcherPayload(BaseModel):
    """Validated structured output from a Bull or Bear researcher.

    Downstream agents (Research Manager, Trader) consume this instead of
    free-text debate transcripts.
    """

    ticker: str
    bias: Literal["PERMABULL", "SHORT_SELLER"] = Field(
        ..., description="The researcher's extreme persona role"
    )
    thesis_summary: str = Field(
        ...,
        description="A highly opinionated, 2-sentence maximum thesis.",
    )
    primary_catalyst: str = Field(
        ...,
        description="The single most important driver for this thesis.",
    )
    supporting_metrics: list[MetricCitation] = Field(
        ...,
        min_length=2,
        description="Must cite at least two exact data points from upstream analysts.",
    )
    target_price: float
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    fatal_flaw_ignored: str = Field(
        ...,
        description="The one major market risk this thesis is intentionally ignoring.",
    )

# ── Fundamentals Analyst ──────────────────────────────────────────


class FundamentalsAnalysis(BaseModel):
    """Structured valuation summary extracted from corporate metrics."""

    ticker: str = Field(..., description="Company ticker symbol")
    valuation_score: float = Field(
        ...,
        ge=1.0,
        le=10.0,
        description="1.0 (extremely undervalued) to 10.0 (extremely overvalued)",
    )
    health_status: Literal["Robust", "Stable", "Vulnerable", "Distressed"] = Field(
        ..., description="Balance-sheet health classification"
    )
    primary_strength: str = Field(
        ..., description="1-sentence description referencing a specific metric"
    )
    primary_weakness: str = Field(
        ..., description="1-sentence description referencing a specific metric"
    )
    overall_fundamental_verdict: Literal["BULLISH", "BEARISH", "NEUTRAL"] = Field(
        ..., description="Overall fundamental outlook"
    )


# ── Market Analyst ────────────────────────────────────────────────


class MarketAnalysis(BaseModel):
    """Structured momentum and trend data from technical indicators."""

    ticker: str = Field(..., description="Company ticker symbol")
    current_trend: Literal[
        "STRONG_UPTREND",
        "WEAK_UPTREND",
        "RANGE_BOUND",
        "WEAK_DOWNTREND",
        "STRONG_DOWNTREND",
    ] = Field(..., description="Primary/secondary trend classification")
    key_support: float = Field(..., description="Immediate support level")
    key_resistance: float = Field(..., description="Immediate resistance level")
    momentum_state: Literal["OVERSOLD", "OVERBOUGHT", "NEUTRAL"] = Field(
        ..., description="RSI / MACD momentum oscillator state"
    )
    institutional_flow_bias: Literal[
        "FII_BULLISH", "DII_BULLISH", "MIXED", "BEARISH"
    ] = Field(..., description="FII/DII net flow directional bias")
    technical_verdict: Literal["BULLISH", "BEARISH", "NEUTRAL"] = Field(
        ..., description="Overall technical outlook"
    )


# ── News Analyst ──────────────────────────────────────────────────


class NewsAnalysis(BaseModel):
    """Quantifiable sentiment score and catalyst extraction from news."""

    ticker: str = Field(..., description="Company ticker symbol")
    sentiment_score: float = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="-1.0 (extreme negative) to 1.0 (extreme positive)",
    )
    catalyst_identified: bool = Field(
        ..., description="Whether a fundamental catalyst was found in the news"
    )
    primary_driver: str = Field(
        ..., description="1-sentence summary of the most impactful news item"
    )
    driver_source: str = Field(
        ...,
        description="Exact substring quote from the provided text that verifies the primary driver",
    )
    news_verdict: Literal["BULLISH", "BEARISH", "NEUTRAL"] = Field(
        ..., description="Overall news sentiment outlook"
    )