import logging

from tradingagents.agents.analysts.schemas import (
    format_analysis_for_prompt,
    ResearcherPayload,
    RESEARCHER_SCHEMA_PROMPT,
    extract_and_validate,
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
    "- CITATION RULE (non-negotiable): Each `supporting_metrics` entry MUST include "
    "the SOURCE ANALYST as a prefix. Format: 'Market: RSI 78 overbought' or "
    "'Fundamentals: Debt/Equity 2.4 (above industry 1.5)' or "
    "'News: SEBI investigation pending'. If an analyst did NOT run, omit that "
    "source. Do NOT fabricate data.\n"
    "- `target_price`: Calculate downside. If market says 'breakdown below support "
    "₹X', set target = X * 0.9. If fundamentals says 'overvalued at PE 40 vs "
    "sector 20', set target = current * (20/40).\n"
    "- `fatal_flaw_ignored`: Pick the SINGLE strongest Bull argument and explain "
    "why it fails in the short-term. Do not list multiple flaws here.\n"
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
            social_sentiment=state.get("social_sentiment"),
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

        # Parse and validate the structured JSON payload — use extract_and_validate
        # for 3-strategy extraction (more robust than direct model_validate_json)
        bear_payload = None
        argument = f"Bear Analyst: {raw_output}"

        bear_payload = extract_and_validate(raw_output, ResearcherPayload, ticker=ticker)
        if bear_payload:
            p = bear_payload
            argument = (
                f"Bear Analyst (SHORT_SELLER) — Thesis: {p.get('thesis_summary', '')}\n"
                f"Catalyst: {p.get('primary_catalyst', '')} | "
                f"Target: ₹{p.get('target_price', '')} | "
                f"Confidence: {float(p.get('confidence_score', 0)):.0%}\n"
                f"Ignored Risk: {p.get('fatal_flaw_ignored', '')}"
            )
            logger.info("Bear Researcher returned valid structured payload for %s", ticker)
        else:
            logger.warning("Bear Researcher payload validation failed for %s", ticker)

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
