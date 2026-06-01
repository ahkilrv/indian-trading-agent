import json
import logging

from tradingagents.agents.analysts.schemas import (
    ResearchManagerVerdict,
    RESEARCH_MANAGER_SCHEMA_PROMPT,
)
from tradingagents.agents.utils.agent_utils import build_instrument_context

logger = logging.getLogger(__name__)

RESEARCH_MANAGER_SYSTEM_PROMPT = (
    "You are the Research Manager for an algorithmic Indian equity fund. "
    "You receive Bull and Bear ResearcherPayload JSON objects and must produce "
    "a definitive, data-grounded verdict.\n\n"
    "DECISION RULES (apply in order):\n"
    "1. Compare Bull's `target_price` and Bear's `target_price`. The thesis "
    "with the stronger `supporting_metrics` (more data-grounded citations, "
    "NOT higher confidence_score) wins.\n"
    "2. If Bull's `confidence_score` > 0.7 AND Bear's `confidence_score` < 0.5 "
    "→ lean BUY. If Bear's `confidence_score` > 0.7 AND Bull's < 0.5 → SELL.\n"
    "3. If Bear's `fatal_flaw_ignored` is confirmed by an analyst source "
    "(check the STRUCTURED ANALYST SCORES section) → weight Bear heavily.\n"
    "4. DO NOT DEFAULT TO HOLD. Pick BUY or SELL unless both sides are equally "
    "compelling with identical data grounding.\n"
    "5. `entry_zone`: Use Bull's target if BUY, Bear's target if SELL. Add a "
    "5% buffer.\n"
    "6. `stop_loss`: If BUY, set at the lower of (Bear's target_price, 2×ATR "
    "below entry). If SELL, set at the higher of (Bull's target_price, 2×ATR "
    "above entry).\n"
    "7. Output ONLY a valid JSON object matching the schema. No conversational filler."
)


def create_research_manager(llm, memory):
    def research_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])
        history = state["investment_debate_state"].get("history", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        investment_debate_state = state["investment_debate_state"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for rec in past_memories:
            past_memory_str += rec["recommendation"] + "\n\n"

        # Include structured payloads for precise comparison
        bull_json = json.dumps(
            state.get("bull_researcher_payload"), indent=2
        ) if state.get("bull_researcher_payload") else "N/A"
        bear_json = json.dumps(
            state.get("bear_researcher_payload"), indent=2
        ) if state.get("bear_researcher_payload") else "N/A"

        prompt = f"""{RESEARCH_MANAGER_SYSTEM_PROMPT}

{RESEARCH_MANAGER_SCHEMA_PROMPT}

=== BULL RESEARCHER THESIS ===
{bull_json}

=== BEAR RESEARCHER THESIS ===
{bear_json}

{instrument_context}

Debate History:
{history}

Past reflections:
{past_memory_str}

Produce your verdict as a JSON object matching the schema above.
"""

        try:
            json_llm = llm.bind(response_format={"type": "json_object"})
        except Exception:
            json_llm = llm

        response = json_llm.invoke(prompt)
        raw_output = response.content if hasattr(response, "content") else str(response)

        rm_verdict = None
        plan_text = raw_output

        try:
            parsed = ResearchManagerVerdict.model_validate_json(raw_output)
            rm_verdict = parsed.model_dump()
            plan_text = (
                f"RECOMMENDATION: {parsed.recommendation}\n"
                f"Entry: {parsed.entry_zone} | SL: ₹{parsed.stop_loss} | "
                f"T1: ₹{parsed.target_1} | T2: ₹{parsed.target_2}\n"
                f"Horizon: {parsed.time_horizon}\n"
                f"Rationale: {parsed.rationale}\n"
                f"Key Risk: {parsed.key_risk}\n"
                f"Bull arguments accepted: {'; '.join(parsed.bull_arguments_accepted)}\n"
                f"Bear arguments accepted: {'; '.join(parsed.bear_arguments_accepted)}"
            )
            logger.info("Research Manager returned valid structured verdict")
        except Exception as exc:
            logger.warning("Research Manager verdict validation failed: %s", exc)

        new_investment_debate_state = {
            "judge_decision": plan_text,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": plan_text,
            "count": investment_debate_state["count"],
        }

        result = {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": plan_text,
        }
        if rm_verdict is not None:
            result["research_manager_verdict"] = rm_verdict

        return result

    return research_manager_node
