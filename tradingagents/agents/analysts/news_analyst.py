from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.schemas import (
    NewsAnalysis,
    extract_and_validate,
)
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_global_news,
    get_language_instruction,
    get_news,
    get_serp_news,
    get_ticker_news,
)

import logging
logger = logging.getLogger(__name__)


NEWS_SYSTEM_PROMPT = """\
You are an expert Financial News Analyst for the Indian market. Your task is to process the provided recent news headlines and articles for the target ticker and output a **strict, valid JSON object** quantifying the market sentiment.

CRITICAL RULES:
1. You are an information extraction engine. Only use the provided text. Do NOT invent facts.
2. CATALYST IDENTIFICATION: A catalyst is a FUNDAMENTAL event that changes the company's outlook — earnings beats, regulatory actions, leadership changes, M&A, major contracts. Routine market commentary is NOT a catalyst.
3. CATALYST PRIORITY: When multiple exist, select the one with largest expected price impact: (1) Regulatory/legal > (2) Earnings/sales > (3) Management > (4) Sector/macro.
4. DRIVER SOURCE (anti-hallucination): For `driver_source`, copy-paste an EXACT sentence from the provided news text. If you cannot find an exact sentence, write "No direct quote available — paraphrased from provided text." NEVER invent a quote.
5. SENTIMENT SCORING: -1.0 = extreme negative (fraud, delisting risk), -0.5 = moderately negative (downgrade, weak results), 0.0 = neutral/mixed, +0.5 = moderately positive (beat, upgrade), +1.0 = extreme positive (blockbuster results, major catalyst).
6. SENTIMENT CALCULATION: Count bullish vs bearish articles. Score = (bullish_count - bearish_count) / total_count, then adjust magnitude by catalyst severity (regulatory ±0.3, earnings ±0.2, other ±0.1).

Do not provide conversational filler, introductions, or markdown outside of the JSON block.
"""


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        instrument_context = build_instrument_context(ticker)

        tools = [
            get_news,
            get_global_news,
            get_serp_news,
            get_ticker_news,
        ]

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=NEWS_SYSTEM_PROMPT)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        try:
            result = chain.invoke(state["messages"])
        except Exception as exc:
            logger.error("[News] FAILED: %s", exc)
            return {
                "messages": state["messages"],
                "news_report": f"News analysis failed: {exc}",
                "news_analysis": None,
            }

        report = ""
        news_analysis = None

        if len(result.tool_calls) == 0:
            report = result.content
            # Attempt structured extraction
            news_analysis = extract_and_validate(
                report,
                NewsAnalysis,
                ticker=ticker,
            )

        return {
            "messages": [result],
            "news_report": report,
            "news_analysis": news_analysis,
        }

    return news_analyst_node