import logging

from tradingagents.agents.analysts.schemas import (
    format_analysis_for_prompt,
    ResearcherPayload,
    RESEARCHER_SCHEMA_PROMPT,
)

logger = logging.getLogger(__name__)

BEAR_SYSTEM_PROMPT = (
    "You are a skeptical, activist Short-Seller operating in the Indian market. "
    "Your sole objective is to ingest the upstream analyst metadata and tear apart "
    "the stock's valuation and technical setup.\n\n"
    "CRITICAL INSTRUCTIONS:\n"
    "- Do not be optimistic. You are hunting for downside risk, mean-reversion, "
    "overbought indicators, and institutional distribution (FII/DII dumping).\n"
    "- Ignore bullish news unless it severely threatens a short position.\n"
    "- Ground your attack by citing at least two negative or overextended metrics "
    "directly from the provided Fundamental, Market, or News data payloads.\n"
    "- You must output ONLY a valid JSON object matching the requested schema. "
    "No conversational filler."
)


def create_bear_researcher(llm, memory):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state.get("market_report", "")
        sentiment_report = state.get("sentiment_report", "")
        news_report = state.get("news_report", "")
        fundamentals_report = state.get("fundamentals_report", "")

        structured_summary = format_analysis_for_prompt(
            market_analysis=state.get("market_analysis"),
            fundamentals_analysis=state.get("fundamentals_analysis"),
            news_analysis=state.get("news_analysis"),
        )

        curr_situation = (
            f"{market_research_report}\n\n"
            f"{sentiment_report}\n\n"
            f"{news_report}\n\n"
            f"{fundamentals_report}"
        )
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        structured_block = ""
        if structured_summary:
            structured_block = (
                "\n\n=== STRUCTURED ANALYST SCORES (VERIFIED) ===\n"
                f"{structured_summary}\n"
                "=== END STRUCTURED SCORES ===\n"
            )

        ticker = state.get("company_of_interest", "UNKNOWN")

        prompt = f"""{BEAR_SYSTEM_PROMPT}

{RESEARCHER_SCHEMA_PROMPT}

Resources available:
Ticker: {ticker}
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest news (Indian & global): {news_report}
Company fundamentals report: {fundamentals_report}
{structured_block}
Conversation history: {history}
Last bull argument: {current_response}
Past reflections and lessons: {past_memory_str}
"""

        try:
            json_llm = llm.bind(response_format={"type": "json_object"})
        except Exception:
            json_llm = llm

        response = json_llm.invoke(prompt)
        raw_output = response.content if hasattr(response, "content") else str(response)

        # Parse and validate the structured JSON payload
        bear_payload = None
        argument = f"Bear Analyst: {raw_output}"

        try:
            parsed = ResearcherPayload.model_validate_json(raw_output)
            bear_payload = parsed.model_dump()
            argument = (
                f"Bear Analyst (SHORT_SELLER) — Thesis: {parsed.thesis_summary}\n"
                f"Catalyst: {parsed.primary_catalyst} | "
                f"Target: ₹{parsed.target_price} | "
                f"Confidence: {parsed.confidence_score:.0%}\n"
                f"Ignored Risk: {parsed.fatal_flaw_ignored}"
            )
            logger.info("Bear Researcher returned valid structured payload for %s", ticker)
        except Exception as exc:
            logger.warning("Bear Researcher payload validation failed for %s: %s", exc)

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "bear_history": bear_history + "\n" + argument,
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        result = {"investment_debate_state": new_investment_debate_state}
        if bear_payload is not None:
            result["bear_researcher_payload"] = bear_payload

        return result

    return bear_node
