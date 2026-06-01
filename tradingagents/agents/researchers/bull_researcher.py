import logging

from tradingagents.agents.analysts.schemas import (
    format_analysis_for_prompt,
    ResearcherPayload,
    RESEARCHER_SCHEMA_PROMPT,
)

logger = logging.getLogger(__name__)

BULL_SYSTEM_PROMPT = (
    "You are a ruthless Permabull equity researcher for the Indian market. "
    "Your sole objective is to ingest the upstream analyst metadata and construct "
    "the strongest possible upside thesis.\n\n"
    "CRITICAL INSTRUCTIONS:\n"
    "- Do not hedge. Do not be balanced. You must find the path to a +20% upside.\n"
    "- Ignore bearish technicals or macroeconomic headwinds unless they make the "
    "upside mathematically impossible.\n"
    "- Ground your thesis by citing at least two positive metrics directly from "
    "the provided Fundamental, Market, or News data payloads.\n"
    "- You must output ONLY a valid JSON object matching the requested schema. "
    "No conversational filler."
)


def create_bull_researcher(llm, memory):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

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

        prompt = f"""{BULL_SYSTEM_PROMPT}

{RESEARCHER_SCHEMA_PROMPT}

Resources available:
Ticker: {ticker}
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest news (Indian & global): {news_report}
Company fundamentals report: {fundamentals_report}
{structured_block}
Conversation history: {history}
Last bear argument: {current_response}
Past reflections and lessons: {past_memory_str}
"""

        try:
            json_llm = llm.bind(response_format={"type": "json_object"})
        except Exception:
            json_llm = llm

        response = json_llm.invoke(prompt)
        raw_output = response.content if hasattr(response, "content") else str(response)

        # Parse and validate the structured JSON payload
        bull_payload = None
        argument = f"Bull Analyst: {raw_output}"

        try:
            parsed = ResearcherPayload.model_validate_json(raw_output)
            bull_payload = parsed.model_dump()
            argument = (
                f"Bull Analyst (PERMABULL) — Thesis: {parsed.thesis_summary}\n"
                f"Catalyst: {parsed.primary_catalyst} | "
                f"Target: ₹{parsed.target_price} | "
                f"Confidence: {parsed.confidence_score:.0%}\n"
                f"Ignored Risk: {parsed.fatal_flaw_ignored}"
            )
            logger.info("Bull Researcher returned valid structured payload for %s", ticker)
        except Exception as exc:
            logger.warning("Bull Researcher payload validation failed for %s: %s", ticker, exc)

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        result = {"investment_debate_state": new_investment_debate_state}
        if bull_payload is not None:
            result["bull_researcher_payload"] = bull_payload

        return result

    return bull_node
