import functools
import json
import logging

from tradingagents.agents.analysts.schemas import (
    TraderExecutionPlan,
    TRADER_SCHEMA_PROMPT,
)
from tradingagents.agents.utils.agent_utils import build_instrument_context

logger = logging.getLogger(__name__)

TRADER_SYSTEM_PROMPT = (
    "You are a short-term trader for the Indian stock market (NSE/BSE). "
    "You convert the Research Manager's investment plan into a specific, "
    "executable order.\n\n"
    "EXECUTION RULES:\n"
    "1. `entry_price`: Use the Research Manager's `entry_zone`. Convert price "
    "ranges to midpoint. If 'at market', set entry_price=0.\n"
    "2. `stop_loss`: Use 2×ATR distance from entry, or the Research Manager's "
    "specified SL — whichever is TIGHTER (closer to entry). Never omit stop-loss.\n"
    "3. `target_1/target_2`: Use Research Manager's targets directly. If missing, "
    "calculate: T1 = entry * 1.05 (BUY) or * 0.95 (SELL). T2 = entry * 1.10 or * 0.90.\n"
    "4. `position_size_pct`: max(0.02, min(0.10, (target_1 - entry) / (entry - stop_loss))) "
    "for BUY. For SELL: same formula with absolute values. Cap at 0.10 (10%).\n"
    "5. `risk_reward_ratio`: (target_1 - entry) / (entry - stop_loss). Must be >= 1.5 "
    "to proceed. If < 1.5, reduce position size by 50%.\n"
    "6. `order_type`: LIMIT if entry is a specific price. MARKET if entry_price=0. "
    "SL-LIMIT if market is volatile (ATR > 3% of price).\n"
    "7. `time_horizon`: Use the Research Manager's horizon.\n"
    "8. Output ONLY a valid JSON object matching the schema. No conversational filler."
)


def create_trader(llm, memory):
    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        investment_plan = state["investment_plan"]
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        if past_memories:
            for rec in past_memories:
                past_memory_str += rec["recommendation"] + "\n\n"
        else:
            past_memory_str = "No past memories found."

        # Include Research Manager structured verdict if available
        rm_verdict_json = json.dumps(
            state.get("research_manager_verdict"), indent=2
        ) if state.get("research_manager_verdict") else "N/A"

        prompt = f"""{TRADER_SYSTEM_PROMPT}

{TRADER_SCHEMA_PROMPT}

=== RESEARCH MANAGER VERDICT ===
{rm_verdict_json}

=== RESEARCH MANAGER PLAN (text) ===
{investment_plan}

{instrument_context}

Past reflections: {past_memory_str}

Produce your execution plan as a JSON object matching the schema above.
"""

        try:
            json_llm = llm.bind(response_format={"type": "json_object"})
        except Exception:
            json_llm = llm

        response = json_llm.invoke(prompt)
        raw_output = response.content if hasattr(response, "content") else str(response)

        trader_payload = None
        plan_text = raw_output

        try:
            parsed = TraderExecutionPlan.model_validate_json(raw_output)
            trader_payload = parsed.model_dump()
            plan_text = (
                f"FINAL TRANSACTION PROPOSAL: **{parsed.action}**\n"
                f"Entry: ₹{parsed.entry_price if parsed.entry_price > 0 else 'MARKET'} | "
                f"SL: ₹{parsed.stop_loss} | "
                f"T1: ₹{parsed.target_1} | T2: ₹{parsed.target_2}\n"
                f"Size: {parsed.position_size_pct:.0%} | "
                f"R:R: {parsed.risk_reward_ratio:.2f} | "
                f"Horizon: {parsed.time_horizon} | "
                f"Order: {parsed.order_type}\n"
                f"Notes: {parsed.execution_notes}"
            )
            logger.info("Trader returned valid structured execution plan for %s", company_name)
        except Exception as exc:
            logger.warning("Trader execution plan validation failed for %s: %s", company_name, exc)

        result = {
            "messages": [response],
            "trader_investment_plan": plan_text,
            "sender": name,
        }
        if trader_payload is not None:
            result["trader_execution_plan"] = trader_payload

        return result

    return functools.partial(trader_node, name="Trader")
