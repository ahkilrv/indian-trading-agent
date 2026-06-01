import json
import logging

from tradingagents.agents.analysts.schemas import (
    NeutralArbitratorPayload,
    NEUTRAL_ARBITRATOR_SCHEMA_PROMPT,
)

logger = logging.getLogger(__name__)

NEUTRAL_SYSTEM_PROMPT = (
    "You are a Neutral Arbitrator — a pure mathematical calculator. "
    "You have NO directional bias and NO opinion on market direction.\n\n"
    "CALCULATION RULES (deterministic):\n"
    "1. `risk_reward_ratio` = (Bull's `target_price` - entry_price) / (entry_price - "
    "Bear's `target_price`). Use the entry_price from the Trader's plan. "
    "If no entry_price is available, use the midpoint of Bull and Bear target prices.\n"
    "2. `verdict`: R:R >= 2.0 → 'BULLISH'. R:R <= 0.5 → 'BEARISH'. "
    "Otherwise → 'NEUTRAL'. No other logic applies.\n"
    "3. Output ONLY a valid JSON object matching the NeutralArbitratorPayload schema. "
    "No conversational filler, no probabilities, no position sizes."
)


def create_neutral_debator(llm):
    def neutral_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        neutral_history = risk_debate_state.get("neutral_history", "")

        current_aggressive_response = risk_debate_state.get(
            "current_aggressive_response", ""
        )
        current_conservative_response = risk_debate_state.get(
            "current_conservative_response", ""
        )

        trader_decision = state.get("trader_investment_plan", "")

        bull_payload = state.get("bull_researcher_payload")
        bear_payload = state.get("bear_researcher_payload")

        bull_json = json.dumps(bull_payload, indent=2) if bull_payload else "{}"
        bear_json = json.dumps(bear_payload, indent=2) if bear_payload else "{}"

        ticker = state.get("company_of_interest", "UNKNOWN")

        prompt = f"""{NEUTRAL_SYSTEM_PROMPT}

{NEUTRAL_ARBITRATOR_SCHEMA_PROMPT}

=== BULL RESEARCHER PAYLOAD (PERMABULL THESIS) ===
{bull_json}

=== BEAR RESEARCHER PAYLOAD (SHORT-SELLER THESIS) ===
{bear_json}

Trader's plan (for entry price): {trader_decision}
Debate history: {history}
Aggressive view: {current_aggressive_response}
Conservative view: {current_conservative_response}

Calculate the R:R ratio and produce your JSON object matching the schema above.
"""

        try:
            json_llm = llm.bind(response_format={"type": "json_object"})
        except Exception:
            json_llm = llm

        response = json_llm.invoke(prompt)
        raw_output = response.content if hasattr(response, "content") else str(response)

        neutral_payload = None
        argument = f"Neutral Analyst: {raw_output}"

        try:
            parsed = NeutralArbitratorPayload.model_validate_json(raw_output)
            neutral_payload = parsed.model_dump()
            argument = (
                f"Neutral Arbitrator — R:R = {parsed.risk_reward_ratio:.2f} | "
                f"Verdict: {parsed.verdict}"
            )
            logger.info(
                "Neutral Arbitrator returned valid R:R calculation for %s — %.2f",
                ticker,
                parsed.risk_reward_ratio,
            )
        except Exception as exc:
            logger.warning(
                "Neutral Arbitrator payload validation failed for %s: %s", ticker, exc
            )

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": neutral_history + "\n" + argument,
            "latest_speaker": "Neutral",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": risk_debate_state.get(
                "current_conservative_response", ""
            ),
            "current_neutral_response": argument,
            "count": risk_debate_state["count"] + 1,
        }

        result = {"risk_debate_state": new_risk_debate_state}
        if neutral_payload is not None:
            result["neutral_debater_payload"] = neutral_payload

        return result

    return neutral_node
