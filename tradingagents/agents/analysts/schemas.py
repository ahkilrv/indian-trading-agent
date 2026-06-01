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


SOCIAL_SENTIMENT_SCHEMA_PROMPT = """\
After your analysis, you MUST output a valid JSON object with exactly these keys:
{
  "ticker": "string — the stock ticker (e.g. RELIANCE.NS)",
  "aggregate_sentiment": "number between -1.0 and 1.0 — overall sentiment from social data",
  "is_high_engagement": "boolean — true if social post volume spiked >2x vs 24h average",
  "sentiment_divergence": "boolean — true if social sentiment contradicts the current price trend",
  "divergence_rationale": "string — one sentence explaining crowd sentiment vs technical reality",
  "social_verdict": "BULLISH | BEARISH | NEUTRAL — your mathematically derived verdict"
}
No other text. No markdown, no explanation, no conversational filler."""

RESEARCH_MANAGER_SCHEMA_PROMPT = """\
You MUST output ONLY a valid JSON object with exactly these keys:
{
  "recommendation": "BUY | SELL | HOLD",
  "rationale": "string — 1-2 sentence verdict grounded in the Bull/Bear debate",
  "entry_zone": "string — price level or range for entry",
  "stop_loss": "number — mandatory stop-loss price",
  "target_1": "number — first profit target",
  "target_2": "number — extended profit target",
  "time_horizon": "INTRADAY | 2_3_DAYS | 1_WEEK | 2_WEEKS",
  "bull_arguments_accepted": ["string bullet 1", "string bullet 2"],
  "bear_arguments_accepted": ["string bullet 1"],
  "key_risk": "string — the single most dangerous risk flagged"
}
No other text. No markdown, no explanation, no conversational filler."""

TRADER_SCHEMA_PROMPT = """\
You MUST output ONLY a valid JSON object with exactly these keys:
{
  "action": "BUY | SELL | HOLD | SHORT",
  "entry_price": "number — specific price or 0 for market entry",
  "stop_loss": "number — mandatory stop-loss, use ATR-based distance",
  "target_1": "number — conservative profit target",
  "target_2": "number — extended target if momentum sustains",
  "position_size_pct": "number between 0.0 and 1.0 — fraction of capital",
  "time_horizon": "INTRADAY | 2_3_DAYS | 1_WEEK | 2_WEEKS",
  "risk_reward_ratio": "number — computed from entry/SL/target_1",
  "order_type": "MARKET | LIMIT | SL-LIMIT",
  "execution_notes": "string — specific execution instructions"
}
No other text. No markdown, no explanation, no conversational filler."""

DEBATER_SCHEMA_PROMPT = """\
You MUST output ONLY a valid JSON object with exactly these keys:
{
  "ticker": "string — the stock ticker (e.g. RELIANCE.NS)",
  "debater_role": "AGGRESSIVE | CONSERVATIVE | NEUTRAL",
  "bull_target_probability": "number between 0.0 and 1.0 — probability Bull target price will be reached in the trade horizon",
  "bear_target_probability": "number between 0.0 and 1.0 — probability Bear target price will be reached in the trade horizon",
  "risk_reward_ratio": "number — the calculated risk-reward ratio (reward / risk)",
  "verdict": "BULLISH | BEARISH | NEUTRAL",
  "position_size_recommendation_pct": "number between 0.0 and 1.0 — fraction of max capital to allocate to this trade",
  "key_rationale": "string — 1-sentence explanation of the verdict based on comparing the two payloads",
  "critical_risk_flagged": "string — the single most dangerous risk that the trade must survive"
}
No other text. No markdown, no explanation, no conversational filler."""

MANAGER_SCHEMA_PROMPT = """\
You MUST output ONLY a valid JSON object with exactly these keys:
{
  "ticker": "string — the stock ticker (e.g. RELIANCE.NS)",
  "rating": "STRONG_BUY | BUY | HOLD | SELL | SHORT",
  "entry_price": "number — exact price level or 0 for market entry",
  "stop_loss": "number — mandatory, specific price level",
  "target_1": "number — first profit-taking level",
  "target_2": "number — extended target if momentum sustains",
  "position_size_pct": "number between 0.0 and 1.0 — fraction of capital to deploy (0.0 = rejected trade)",
  "time_horizon": "INTRADAY | 2_3_DAYS | 1_WEEK | 2_WEEKS",
  "risk_reward_ratio": "number — computed from entry/SL/target_1",
  "confidence_score": "number between 0.0 and 1.0",
  "executive_summary": "string — concise action plan with key risk levels (max 2 sentences)",
  "investment_thesis": "string — detailed reasoning from downstream payloads",
  "rejection_reason": "string — REQUIRED if rating is HOLD or SELL; otherwise empty string"
}
No other text. No markdown, no explanation, no conversational filler."""

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
    social_sentiment: Optional[dict[str, Any]] = None,
) -> str:
    """Render structured analysis dicts as a concise text block for LLM prompts.

    Returns an empty string if no analysis dicts are provided.
    """
    blocks: list[str] = []

    if market_analysis:
        support_vals = market_analysis.get("key_support", [])
        resistance_vals = market_analysis.get("key_resistance", [])
        if isinstance(support_vals, list):
            sup_str = ", ".join(f"S{i+1}:₹{v}" for i, v in enumerate(support_vals[:3]))
        else:
            sup_str = str(support_vals)
        if isinstance(resistance_vals, list):
            res_str = ", ".join(f"R{i+1}:₹{v}" for i, v in enumerate(resistance_vals[:3]))
        else:
            res_str = str(resistance_vals)

        blocks.append(
            "Structured Market Analysis:\n"
            f"  Ticker: {market_analysis.get('ticker', 'N/A')}\n"
            f"  Trend: {market_analysis.get('current_trend', 'N/A')}\n"
            f"  Support: {sup_str}\n"
            f"  Resistance: {res_str}\n"
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

    if social_sentiment:
        blocks.append(
            "Structured Social Sentiment Analysis:\n"
            f"  Ticker: {social_sentiment.get('ticker', 'N/A')}\n"
            f"  Aggregate Sentiment (-1 to +1): {social_sentiment.get('aggregate_sentiment', 'N/A')}\n"
            f"  High Engagement: {social_sentiment.get('is_high_engagement', 'N/A')}\n"
            f"  Sentiment Divergence: {social_sentiment.get('sentiment_divergence', 'N/A')}\n"
            f"  Divergence Rationale: {social_sentiment.get('divergence_rationale', 'N/A')}\n"
            f"  Social Verdict: {social_sentiment.get('social_verdict', 'N/A')}"
        )

    return "\n\n".join(blocks)


class SocialSentimentPayload(BaseModel):
    """Structured sentiment-divergence report from social media analysis."""

    ticker: str
    aggregate_sentiment: float = Field(ge=-1.0, le=1.0)
    is_high_engagement: bool
    sentiment_divergence: bool
    divergence_rationale: str
    social_verdict: Literal["BULLISH", "BEARISH", "NEUTRAL"]


class ResearchManagerVerdict(BaseModel):
    """Structured output from the Research Manager who judges Bull vs Bear debate."""

    recommendation: Literal["BUY", "SELL", "HOLD"] = Field(
        ..., description="Definitive trade direction"
    )
    rationale: str = Field(
        ..., max_length=300, description="1-2 sentence verdict grounded in debate"
    )
    entry_zone: str = Field(..., description="Specific price level or range for entry")
    stop_loss: float = Field(..., description="Mandatory stop-loss price")
    target_1: float = Field(..., description="First profit target")
    target_2: float = Field(..., description="Extended profit target")
    time_horizon: Literal["INTRADAY", "2_3_DAYS", "1_WEEK", "2_WEEKS"] = Field(
        ..., description="Expected holding period"
    )
    bull_arguments_accepted: list[str] = Field(
        ..., min_length=1, description="Bull arguments that won the debate"
    )
    bear_arguments_accepted: list[str] = Field(
        default_factory=list, description="Bear arguments acknowledged as valid risks"
    )
    key_risk: str = Field(..., description="Single most dangerous risk flagged")


class TraderExecutionPlan(BaseModel):
    """Structured execution plan from the Trader agent."""

    action: Literal["BUY", "SELL", "HOLD", "SHORT"] = Field(
        ..., description="Trade action"
    )
    entry_price: float = Field(
        ..., description="Specific entry price or 0 for market entry"
    )
    stop_loss: float = Field(..., description="Mandatory stop-loss, ATR-based distance")
    target_1: float = Field(..., description="Conservative profit target")
    target_2: float = Field(..., description="Extended target")
    position_size_pct: float = Field(..., ge=0.0, le=1.0)
    time_horizon: Literal["INTRADAY", "2_3_DAYS", "1_WEEK", "2_WEEKS"]
    risk_reward_ratio: float
    order_type: Literal["MARKET", "LIMIT", "SL-LIMIT"]
    execution_notes: str = Field(..., max_length=200)


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


class DebaterPayload(BaseModel):
    """Validated structured output from a Risk Debater (Aggressive / Conservative / Neutral).

    The debater ingests both Bull and Bear ResearcherPayloads and produces
    a single risk-weighted verdict with position-sizing guidance.
    """

    ticker: str
    debater_role: Literal["AGGRESSIVE", "CONSERVATIVE", "NEUTRAL"] = Field(
        ..., description="Which risk persona produced this payload"
    )
    bull_target_probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Estimated probability the Bull target price is reached within the trade horizon",
    )
    bear_target_probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Estimated probability the Bear target price is reached within the trade horizon",
    )
    risk_reward_ratio: float = Field(
        ...,
        description="Computed risk-reward ratio (reward / risk)",
    )
    verdict: Literal["BULLISH", "BEARISH", "NEUTRAL"] = Field(
        ..., description="Directional verdict after comparing both payloads"
    )
    position_size_recommendation_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of max allocated capital to commit (0.0 = skip, 1.0 = full size)",
    )
    key_rationale: str = Field(
        ...,
        description="1-sentence explanation grounded in the two provided payloads",
    )
    critical_risk_flagged: str = Field(
        ...,
        description="The single most dangerous risk the trade must survive to succeed",
    )


class ConservativeVetoPayload(DebaterPayload):
    """Conservative Risk Officer output — extends DebaterPayload with structural risk assessment.

    Only used by the Conservative Risk Officer.  The Aggressive and Neutral
    debaters continue to use the base DebaterPayload.
    """

    debater_role: Literal["CONSERVATIVE"] = Field(
        default="CONSERVATIVE",
        description="Locked to CONSERVATIVE for this risk persona",
    )
    structural_risk: bool = Field(
        ...,
        description="True if a significant structural risk is identified (regulatory, "
        "macroeconomic, major fundamental weakness, extreme volatility)",
    )
    probability_of_structural_risk: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Assessed likelihood of the structural risk manifesting",
    )
    veto_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in the structural risk assessment and veto decision",
    )
    rejection_reason: str = Field(
        ...,
        description="Detailed, evidence-based reason for rejection. "
        "Must cite specific fields from upstream analyst payloads when veto triggers. "
        "Leave empty if no veto.",
    )


CONSERVATIVE_VETO_SCHEMA_PROMPT = """\
You MUST output ONLY a valid JSON object with exactly these keys:
{
  "ticker": "string — the stock ticker (e.g. RELIANCE.NS)",
  "debater_role": "Must be 'CONSERVATIVE'",
  "bull_target_probability": "number between 0.0 and 1.0",
  "bear_target_probability": "number between 0.0 and 1.0",
  "risk_reward_ratio": "number — computed risk-reward ratio",
  "verdict": "BULLISH | BEARISH | NEUTRAL",
  "position_size_recommendation_pct": "number between 0.0 and 1.0 — set to 0.0 if veto triggers",
  "key_rationale": "string — 1-sentence explanation",
  "critical_risk_flagged": "string — the single most dangerous risk",
  "structural_risk": "boolean — true if a significant structural risk exists",
  "probability_of_structural_risk": "number between 0.0 and 1.0 — how likely the risk manifests",
  "veto_confidence": "number between 0.0 and 1.0 — your confidence in this assessment",
  "rejection_reason": "string — REQUIRED if structural_risk is true AND probability > 0.80 AND veto_confidence > 0.80. Cite specific analyst fields. Leave empty otherwise."
}
No other text. No markdown, no explanation, no conversational filler."""

NEUTRAL_ARBITRATOR_SCHEMA_PROMPT = """\
You MUST output ONLY a valid JSON object with exactly these keys:
{
  "ticker": "string — the stock ticker (e.g. RELIANCE.NS)",
  "debater_role": "Must be 'NEUTRAL'",
  "risk_reward_ratio": "number — (Bull target_price - entry_price) / (entry_price - Bear target_price)",
  "verdict": "BULLISH if R:R >= 2.0 | BEARISH if R:R <= 0.5 | NEUTRAL otherwise"
}
No other text. No markdown, no explanation, no conversational filler."""


class NeutralArbitratorPayload(BaseModel):
    """Pure mathematical R:R calculator. No opinion, no probabilities, no verdict guesswork.

    Only the Neutral Agent uses this. It computes the risk-reward ratio from
    Bull and Bear target prices and derives a deterministic verdict.
    """

    ticker: str
    debater_role: Literal["NEUTRAL"] = Field(default="NEUTRAL")
    risk_reward_ratio: float = Field(
        ...,
        ge=0.0,
        description="(Bull target_price - entry) / (entry - Bear target_price)",
    )
    verdict: Literal["BULLISH", "BEARISH", "NEUTRAL"] = Field(
        ...,
        description="Deterministic: R:R >= 2.0 → BULLISH, R:R <= 0.5 → BEARISH, else NEUTRAL",
    )


class ManagerExecutionPayload(BaseModel):
    """Final structured execution order from the Portfolio Manager.

    This is the terminal node in the agent pipeline.  It ingests three
    DebaterPayloads (Aggressive / Conservative / Neutral) and produces a
    single machine-readable trade instruction with hard numeric levels.
    """

    ticker: str
    rating: Literal["STRONG_BUY", "BUY", "HOLD", "SELL", "SHORT"] = Field(
        ..., description="Final trade rating"
    )
    entry_price: float = Field(
        ..., description="Specific entry price level, or 0 for market entry"
    )
    stop_loss: float = Field(
        ..., description="Mandatory stop-loss price level"
    )
    target_1: float = Field(
        ..., description="First profit-taking price target"
    )
    target_2: float = Field(
        ..., description="Extended profit target if momentum sustains"
    )
    position_size_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of trading capital to deploy (0.0 = rejected trade)",
    )
    time_horizon: Literal["INTRADAY", "2_3_DAYS", "1_WEEK", "2_WEEKS"] = Field(
        ..., description="Expected holding period"
    )
    risk_reward_ratio: float = Field(
        ..., description="Computed from entry / stop-loss / target_1"
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Portfolio Manager's confidence in this decision",
    )
    executive_summary: str = Field(
        ...,
        max_length=300,
        description="Concise action plan with key risk levels (max 2 sentences)",
    )
    investment_thesis: str = Field(
        ..., description="Detailed reasoning grounded in downstream debater payloads"
    )
    rejection_reason: str = Field(
        default="",
        description="Required if rating is HOLD or SELL; otherwise empty",
    )


# ── Fundamentals Analyst ──────────────────────────────────────────


class FundamentalsAnalysis(BaseModel):
    """Structured valuation summary extracted from corporate metrics."""

    ticker: str = Field(..., description="Company ticker symbol")
    valuation_score: int = Field(
        ...,
        ge=1,
        le=10,
        description="1 (extremely undervalued) to 10 (extremely overvalued) — whole numbers only",
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
    key_support: list[float] = Field(
        ..., min_length=1, description="Support levels S1,S2,S3 from closest to furthest"
    )
    key_resistance: list[float] = Field(
        ..., min_length=1, description="Resistance levels R1,R2,R3 from closest to furthest"
    )
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