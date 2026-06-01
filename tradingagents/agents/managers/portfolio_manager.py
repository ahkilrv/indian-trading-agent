import json
import logging

from tradingagents.agents.analysts.schemas import (
    ManagerExecutionPayload,
    MANAGER_SCHEMA_PROMPT,
)
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)

logger = logging.getLogger(__name__)

PORTFOLIO_MANAGER_SYSTEM_PROMPT = (
    "You are the Chief Portfolio Manager for an algorithmic Indian equity fund. "
    "You are the final execution arbiter. You will be provided with structured JSON "
    "payloads from three Risk Officers (Aggressive, Conservative, Neutral).\n\n"
    "EXECUTION CHECKLIST (follow in ORDER — do not skip steps):\n\n"
    "STEP 1 — CONSERVATIVE VETO (deterministic — IGNORE ALL OTHER INPUTS):\n"
    "IF Conservative Risk Officer's `structural_risk` == true\n"
    "AND `probability_of_structural_risk` > 0.80\n"
    "AND `veto_confidence` > 0.80:\n"
    "→ IMMEDIATELY HALT. DO NOT PROCEED TO STEPS 2 OR 3. DO NOT CALCULATE TARGETS.\n\n"
    "Output ONLY this rejection JSON and STOP:\n"
    "{\n"
    "  \"ticker\": \"<from input>\",\n"
    "  \"rating\": \"HOLD\",\n"
    "  \"entry_price\": 0,\n"
    "  \"stop_loss\": 0,\n"
    "  \"target_1\": 0,\n"
    "  \"target_2\": 0,\n"
    "  \"position_size_pct\": 0.0,\n"
    "  \"time_horizon\": \"1_WEEK\",\n"
    "  \"risk_reward_ratio\": 0,\n"
    "  \"confidence_score\": 0.3,\n"
    "  \"executive_summary\": \"Trade rejected by Conservative Risk Officer veto.\",\n"
    "  \"investment_thesis\": \"DO NOT ENTER.\",\n"
    "  \"rejection_reason\": \"<Conservative's rejection_reason field verbatim>\"\n"
    "}\n\n"
    "STEP 2 — MAJORITY VERDICT (only if Conservative did NOT veto):\n"
    "Compare Aggressive and Neutral verdicts.\n"
    "- If 2 of 3 debaters agree on same direction → use their consensus.\n"
    "- If all 3 disagree → Neutral is the tiebreaker.\n"
    "- If Conservative has structural_risk=true but did not meet BOTH threshold "
    "criteria (> 0.80), and BOTH Aggressive AND Neutral are BULLISH → may proceed "
    "at reduced size (max 0.25).\n\n"
    "STEP 3 — HARD NUMBERS (only if trade proceeds):\n"
    "- `entry_price`: Midpoint of Bull and Bear target prices, or current price from Market Analysis.\n"
    "- `stop_loss`: Lower of Bear's `target_price` OR 2×ATR distance below entry. Never skip.\n"
    "- `target_1`: Bull's `target_price` discounted by (1 - Bull's `confidence_score`).\n"
    "- `target_2`: Bull's `target_price` if confidence > 0.8, else Bull_target * 1.05.\n"
    "- `position_size_pct`: Conservative's recommendation if veto not triggered; "
    "otherwise average of Aggressive and Neutral (capped at 0.25 if Conservative was BEARISH).\n"
    "- `confidence_score`: Average of Aggressive and Neutral `bull_target_probability` "
    "minus Conservative's `bear_target_probability` * 0.5.\n\n"
    "4. Output ONLY a valid JSON object matching the ManagerExecutionPayload schema. "
    "No conversational filler."
)


def create_portfolio_manager(llm, memory):
    def portfolio_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        market_research_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        sentiment_report = state["sentiment_report"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]

        curr_situation = (
            f"{market_research_report}\n\n"
            f"{sentiment_report}\n\n"
            f"{news_report}\n\n"
            f"{fundamentals_report}"
        )
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for rec in past_memories:
            past_memory_str += rec["recommendation"] + "\n\n"

        # ── Ingest structured payloads from upstream nodes ──
        bull_payload = state.get("bull_researcher_payload")
        bear_payload = state.get("bear_researcher_payload")
        aggressive_payload = state.get("aggressive_debater_payload")
        conservative_payload = state.get("conservative_debater_payload")
        neutral_payload = state.get("neutral_debater_payload")

        bull_json = json.dumps(bull_payload, indent=2) if bull_payload else "N/A"
        bear_json = json.dumps(bear_payload, indent=2) if bear_payload else "N/A"
        aggressive_json = (
            json.dumps(aggressive_payload, indent=2) if aggressive_payload else "N/A"
        )
        conservative_json = (
            json.dumps(conservative_payload, indent=2)
            if conservative_payload
            else "N/A"
        )
        neutral_json = (
            json.dumps(neutral_payload, indent=2) if neutral_payload else "N/A"
        )

        ticker = state.get("company_of_interest", "UNKNOWN")

        prompt = f"""{PORTFOLIO_MANAGER_SYSTEM_PROMPT}

{MANAGER_SCHEMA_PROMPT}

{instrument_context}

=== UPSTREAM RESEARCHER THESES ===
=== BULL RESEARCHER PAYLOAD (PERMABULL) ===
{bull_json}

=== BEAR RESEARCHER PAYLOAD (SHORT-SELLER) ===
{bear_json}

=== RISK DEBATER ASSESSMENTS ===
=== AGGRESSIVE RISK OFFICER ===
{aggressive_json}

=== CONSERVATIVE RISK OFFICER ===
{conservative_json}

=== NEUTRAL ARBITRATOR ===
{neutral_json}

=== ADDITIONAL CONTEXT ===
Research Manager plan: {research_plan}
Trader transaction proposal: {trader_plan}
Past reflections and lessons: {past_memory_str}

Produce your final execution order as a JSON object matching the schema above.{get_language_instruction()}
"""

        try:
            json_llm = llm.bind(response_format={"type": "json_object"})
        except Exception:
            json_llm = llm

        response = json_llm.invoke(prompt)
        raw_output = (
            response.content if hasattr(response, "content") else str(response)
        )

        # Parse and validate the structured JSON payload
        pm_payload = None
        final_decision_text = raw_output

        try:
            parsed = ManagerExecutionPayload.model_validate_json(raw_output)
            pm_payload = parsed.model_dump()
            # Build a human-readable summary string for the legacy final_trade_decision field
            final_decision_text = (
                f"RATING: {parsed.rating}\n"
                f"Entry: {parsed.entry_price} | "
                f"SL: {parsed.stop_loss} | "
                f"T1: {parsed.target_1} | "
                f"T2: {parsed.target_2}\n"
                f"Position Size: {parsed.position_size_pct:.0%} | "
                f"Horizon: {parsed.time_horizon} | "
                f"R:R: {parsed.risk_reward_ratio:.2f} | "
                f"Confidence: {parsed.confidence_score:.0%}\n"
                f"Summary: {parsed.executive_summary}\n"
                f"Thesis: {parsed.investment_thesis}\n"
                f"Rejection: {parsed.rejection_reason or 'N/A'}"
            )
            logger.info(
                "Portfolio Manager returned valid structured payload for %s — rating: %s",
                ticker,
                parsed.rating,
            )
        except Exception as exc:
            logger.warning(
                "Portfolio Manager payload validation failed for %s: %s", ticker, exc
            )

        new_risk_debate_state = {
            "judge_decision": final_decision_text,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state[
                "current_aggressive_response"
            ],
            "current_conservative_response": risk_debate_state[
                "current_conservative_response"
            ],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        result = {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_decision_text,
        }
        if pm_payload is not None:
            result["portfolio_manager_payload"] = pm_payload

        return result

    return portfolio_manager_node
