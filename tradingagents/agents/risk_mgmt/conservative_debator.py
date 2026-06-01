import json
import logging

from tradingagents.agents.analysts.schemas import (
    ConservativeVetoPayload,
    CONSERVATIVE_VETO_SCHEMA_PROMPT,
)

logger = logging.getLogger(__name__)

CONSERVATIVE_SYSTEM_PROMPT = (
    "You are a Conservative Risk Officer for an Indian equity fund. "
    "You will be provided with two structured JSON payloads: a Permabull thesis "
    "and a Short-Seller thesis.\n\n"
    "CRITICAL INSTRUCTIONS:\n"
    "1. Capital preservation is your ONLY goal. You have zero tolerance for "
    "unquantifiable risk.\n"
    "2. STRUCTURAL RISK ASSESSMENT: Evaluate whether any of these structural "
    "risks exist: (i) regulatory/legal threats (SEBI, RBI, court rulings), "
    "(ii) severe fundamental weakness (Distressed health, negative FCF + high debt), "
    "(iii) market-wide extreme volatility (VIX > 30, FII panic selling), "
    "(iv) macro shocks (crude oil spike, INR crash, geopolitical event impacting India).\n"
    "3. VETO RULES (deterministic — if ANY triggers, set structural_risk=true AND "
    "verdict=BEARISH AND position_size_recommendation_pct=0.0):\n"
    "   a) Regulatory/legal risk confirmed in upstream data AND "
    "probability_of_structural_risk > 0.80 AND veto_confidence > 0.80 → veto.\n"
    "   b) Fundamentals 'health_status' is Distressed or Vulnerable AND "
    "probability_of_structural_risk > 0.70 → veto.\n"
    "   c) Market 'momentum_state' is OVERBOUGHT AND Social confirms "
    "'sentiment_divergence' is true AND probability_of_structural_risk > 0.75 → veto.\n"
    "   d) Bear's 'supporting_metrics' count >= 3 (strong short case) AND "
    "probability_of_structural_risk > 0.80 → veto.\n"
    "4. PROBABILITY GUIDANCE: Set `probability_of_structural_risk` by evaluating "
    "how many Bear metrics align with analyst verdicts. Start at 0.50 baseline. "
    "Add 0.10 for each analyst whose verdict matches the Bear. Add 0.15 if Bear's "
    "'fatal_flaw_ignored' references a risk confirmed by an analyst. Cap at 0.95.\n"
    "5. `rejection_reason`: When veto triggers, provide a detailed, evidence-based "
    "reason citing specific fields from upstream analyst payloads (e.g., "
    "'Fundamentals: health_status=Distressed, P/E=45 vs sector 20'). "
    "Leave empty if no veto.\n"
    "6. If NONE of the veto rules trigger, set structural_risk=false, "
    "position_size_recommendation_pct = max(0.10, 0.25 - probability_of_structural_risk) "
    "and verdict based on which thesis has stronger data grounding.\n"
    "7. You act as a JSON data transformation node. Output ONLY a valid JSON "
    "object matching the ConservativeVetoPayload schema. No conversational filler."
)


def create_conservative_debator(llm):
    def conservative_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        conservative_history = risk_debate_state.get("conservative_history", "")

        current_aggressive_response = risk_debate_state.get(
            "current_aggressive_response", ""
        )
        current_neutral_response = risk_debate_state.get(
            "current_neutral_response", ""
        )

        trader_decision = state.get("trader_investment_plan", "")

        bull_payload = state.get("bull_researcher_payload")
        bear_payload = state.get("bear_researcher_payload")

        bull_json = json.dumps(bull_payload, indent=2) if bull_payload else "{}"
        bear_json = json.dumps(bear_payload, indent=2) if bear_payload else "{}"

        ticker = state.get("company_of_interest", "UNKNOWN")

        prompt = f"""{CONSERVATIVE_SYSTEM_PROMPT}

{CONSERVATIVE_VETO_SCHEMA_PROMPT}

=== BULL RESEARCHER PAYLOAD (PERMABULL THESIS) ===
{bull_json}

=== BEAR RESEARCHER PAYLOAD (SHORT-SELLER THESIS) ===
{bear_json}

Trader's decision: {trader_decision}
Debate history: {history}
Aggressive view: {current_aggressive_response}
Neutral view: {current_neutral_response}

Produce your Conservative risk assessment as a JSON object matching the schema above.
"""

        try:
            json_llm = llm.bind(response_format={"type": "json_object"})
        except Exception:
            json_llm = llm

        response = json_llm.invoke(prompt)
        raw_output = response.content if hasattr(response, "content") else str(response)

        # Parse and validate the structured JSON payload
        conservative_payload = None
        argument = f"Conservative Analyst: {raw_output}"

        try:
            parsed = ConservativeVetoPayload.model_validate_json(raw_output)
            conservative_payload = parsed.model_dump()
            veto_status = "VETOED" if parsed.structural_risk else "PASSED"
            argument = (
                f"Conservative Risk Officer [{veto_status}] — "
                f"Structural Risk: {parsed.structural_risk} | "
                f"Prob: {parsed.probability_of_structural_risk:.0%} | "
                f"Confidence: {parsed.veto_confidence:.0%} | "
                f"Verdict: {parsed.verdict} | "
                f"Size: {parsed.position_size_recommendation_pct:.0%}\n"
                f"Rejection: {parsed.rejection_reason or 'N/A'}"
            )
            logger.info(
                "Conservative Debater returned valid payload for %s — veto=%s",
                ticker,
                parsed.structural_risk,
            )
        except Exception as exc:
            logger.warning(
                "Conservative Debater payload validation failed for %s: %s",
                ticker,
                exc,
            )

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": conservative_history + "\n" + argument,
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Conservative",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": argument,
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        result = {"risk_debate_state": new_risk_debate_state}
        if conservative_payload is not None:
            result["conservative_debater_payload"] = conservative_payload

        return result

    return conservative_node
