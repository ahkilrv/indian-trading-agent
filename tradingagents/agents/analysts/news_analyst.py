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
)


NEWS_SYSTEM_PROMPT = """\
You are an expert Financial News Analyst. Your task is to process the provided recent news headlines and articles for the target ticker and output a **strict, valid JSON object** quantifying the market sentiment.

You must act as a precise information extraction engine. Only consider the provided text. Do **not** provide conversational filler, introductions, or markdown formatting outside of the JSON block.

Evaluation Criteria:
- Determine if the news contains fundamental catalysts (e.g., earnings beats, leadership changes, regulatory approvals).
- Score the overall sentiment objectively.
- Identify the single most impactful news driver.

Output Schema Requirement:
```json
{
  "ticker": "<String>",
  "sentiment_score": "<Float between -1.0 (extreme negative) to 1.0 (extreme positive)>",
  "catalyst_identified": "<Boolean>",
  "primary_driver": "<String: 1-sentence summary of the most impactful news item>",
  "driver_source": "<String: Exact substring quote from the provided text verifying the primary driver>",
  "news_verdict": "<String: 'BULLISH' | 'BEARISH' | 'NEUTRAL'>"
}
```

After the JSON block you may optionally append a Markdown table summarizing key news items for human readability.
"""


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        instrument_context = build_instrument_context(ticker)

        tools = [
            get_news,
            get_global_news,
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
        result = chain.invoke(state["messages"])

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