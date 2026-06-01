import logging

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.schemas import (
    SocialSentimentPayload,
    SOCIAL_SENTIMENT_SCHEMA_PROMPT,
    extract_and_validate,
)
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_forums_sentiment,
    get_language_instruction,
    get_news,
    get_trends,
    get_youtube_sentiment,
)
from tradingagents.dataflows.config import get_config

logger = logging.getLogger(__name__)

SOCIAL_SYSTEM_PROMPT = (
    "You are an expert Social Media Arbitrage Analyst for the Indian market. "
    "Your task is to ingest raw social data (from StockTwits and X cashtags) "
    "for the target ticker and identify 'Sentiment Divergence' — instances where "
    "social sentiment contradicts the actual price trend.\n\n"
    "CRITICAL INSTRUCTIONS:\n"
    "- Act as a data-transformation node. Output ONLY a valid JSON object matching "
    "the SocialSentimentPayload schema. No conversational filler.\n"
    "- Focus on 'Sentiment Divergence': If the stock price is at a 52-week high "
    "but sentiment is turning 'Bearish' (distrust), highlight this as a potential "
    "reversal signal.\n"
    "- If social volume (post frequency) has spiked >200% compared to the 24-hour "
    "moving average, set is_high_engagement = true.\n"
    "- Your verdict must be mathematically derived from the sentiment score."
)


def create_social_media_analyst(llm):
    def social_media_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        instrument_context = build_instrument_context(ticker)

        tools = [
            get_news,
            get_trends,
            get_youtube_sentiment,
            get_forums_sentiment,
        ]

        system_message = (
            f"{SOCIAL_SYSTEM_PROMPT}\n"
            + get_language_instruction()
            + f"\n\n{SOCIAL_SENTIMENT_SCHEMA_PROMPT}"
        )

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

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        try:
            result = chain.invoke(state["messages"])
        except Exception as exc:
            logger.error("[Social] FAILED: %s", exc)
            return {
                "messages": state["messages"],
                "sentiment_report": f"Social sentiment analysis failed: {exc}",
                "social_sentiment": None,
            }

        report = ""
        social_sentiment = None

        if len(result.tool_calls) == 0:
            report = result.content
            social_sentiment = extract_and_validate(
                report,
                SocialSentimentPayload,
                ticker=ticker,
            )

        return {
            "messages": [result],
            "sentiment_report": report,
            "social_sentiment": social_sentiment,
        }

    return social_media_analyst_node
