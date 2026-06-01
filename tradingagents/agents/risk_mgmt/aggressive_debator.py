import json
import logging

from tradingagents.agents.analysts.schemas import (
    DebaterPayload,
    DEBATER_SCHEMA_PROMPT,
)

logger = logging.getLogger(__name__)

AGGRESSIVE_SYSTEM_PROMPT = (
    "You are an Aggressive Risk Officer for an Indian equity fund. "
    "You will be provided with two structured JSON payloads: a Permabull thesis "
    "and a Short-Seller thesis.\n\n"
    "CRITICAL INSTRUCTIONS:\n"
    "1. You have a high risk tolerance. You favor momentum, upside breakouts, "
    "and high-conviction catalysts.\n"
    "2. PROBABILITY CALCULATION: Set `bull_target_probability` based on how many "
    "of the Bull's `supporting_metrics` align with analyst verdicts. "
    "Start at 0.50 baseline. Add 0.10 for each analyst whose verdict matches "
    "the Bull's direction (Market BULLISH = +0.10, Fundamentals BULLISH = +0.10, "
    "News BULLISH = +0.10). Cap at 0.90.\n"
    "3. POSITION SIZING: Set `position_size_recommendation_pct` to 0.8-1.0 if "
    "at least 2 of 3: (a) Bull confidence > 0.7, (b) RSI not overbought from "
    "Market data, (c) positive catalyst in News analysis. Otherwise scale down "
    "to 0.4-0.7.\n"
    "4. If the Bull's 'primary_catalyst' mathematically outweighs the Bear's "
    "'fatal_flaw_ignored', lean BULLISH.\n"
    "5. You act as a JSON data transformation node. Output ONLY a valid JSON "
    "object matching the DebaterPayload schema. No conversational filler."
)


def create_aggressive_debator(llm):
    def aggressive_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        aggressive_history = risk_debate_state.get("aggressive_history", "")

        current_conservative_response = risk_debate_state.get(
            "current_conservative_response", ""
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

        prompt = f"""{AGGRESSIVE_SYSTEM_PROMPT}

{DEBATER_SCHEMA_PROMPT}

=== BULL RESEARCHER PAYLOAD (PERMABULL THESIS) ===
{bull_json}

=== BEAR RESEARCHER PAYLOAD (SHORT-SELLER THESIS) ===
{bear_json}

Trader's decision: {trader_decision}
Debate history: {history}
Conservative view: {current_conservative_response}
Neutral view: {current_neutral_response}

Produce your Aggressive risk assessment as a JSON object matching the schema above.
"""

        try:
            json_llm = llm.bind(response_format={"type": "json_object"})
        except Exception:
            json_llm = llm

        response = json_llm.invoke(prompt)
        raw_output = response.content if hasattr(response, "content") else str(response)

        # Parse and validate the structured JSON payload
        aggressive_payload = None
        argument = f"Aggressive Analyst: {raw_output}"

        try:
            parsed = DebaterPayload.model_validate_json(raw_output)
            aggressive_payload = parsed.model_dump()
            argument = (
                f"Aggressive Risk Officer — Verdict: {parsed.verdict} | "
                f"R:R = {parsed.risk_reward_ratio:.2f} | "
                f"Size: {parsed.position_size_recommendation_pct:.0%} | "
                f"Bull Prob: {parsed.bull_target_probability:.0%} | "
                f"Bear Prob: {parsed.bear_target_probability:.0%}\n"
                f"Rationale: {parsed.key_rationale}\n"
                f"Critical Risk: {parsed.critical_risk_flagged}"
            )
            logger.info(
                "Aggressive Debater returned valid structured payload for %s", ticker
            )
        except Exception as exc:
            logger.warning(
                "Aggressive Debater payload validation failed for %s: %s", ticker, exc
            )

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": aggressive_history + "\n" + argument,
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Aggressive",
            "current_aggressive_response": argument,
            "current_conservative_response": risk_debate_state.get(
                "current_conservative_response", ""
            ),
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        result = {"risk_debate_state": new_risk_debate_state}
        if aggressive_payload is not None:
            result["aggressive_debater_payload"] = aggressive_payload

        return result

    return aggressive_node
