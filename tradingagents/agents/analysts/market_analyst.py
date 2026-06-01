from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.schemas import (
    MarketAnalysis,
    extract_and_validate,
)
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_indicators,
    get_language_instruction,
    get_stock_data,
)


MARKET_SYSTEM_PROMPT = """\
You are an expert Quantitative Market Analyst specializing in the NSE. Your task is to process the provided price action, moving averages, momentum oscillators (RSI, MACD), and institutional flows, outputting the analysis as a **strict, valid JSON object**.

Base your conclusions strictly on the provided technical data. Do **not** guess or infer macroeconomic conditions. Do **not** provide conversational filler, introductions, or markdown formatting outside of the JSON block.

Evaluation Criteria:
- Identify the primary and secondary trends.
- Pinpoint immediate support and resistance levels.
- Evaluate momentum convergence or divergence.

Output Schema Requirement:
```json
{
  "ticker": "<String>",
  "current_trend": "<String: 'STRONG_UPTREND' | 'WEAK_UPTREND' | 'RANGE_BOUND' | 'WEAK_DOWNTREND' | 'STRONG_DOWNTREND'>",
  "key_support": "<Float>",
  "key_resistance": "<Float>",
  "momentum_state": "<String: 'OVERSOLD' | 'OVERBOUGHT' | 'NEUTRAL'>",
  "institutional_flow_bias": "<String: 'FII_BULLISH' | 'DII_BULLISH' | 'MIXED' | 'BEARISH'>",
  "technical_verdict": "<String: 'BULLISH' | 'BEARISH' | 'NEUTRAL'>"
}
```

After the JSON block you may optionally append a Markdown table summarizing key technical indicators for human readability.
"""


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        instrument_context = build_instrument_context(ticker)

        tools = [
            get_stock_data,
            get_indicators,
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

        prompt = prompt.partial(system_message=MARKET_SYSTEM_PROMPT)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""
        market_analysis = None

        if len(result.tool_calls) == 0:
            report = result.content
            # Attempt structured extraction
            market_analysis = extract_and_validate(
                report,
                MarketAnalysis,
                ticker=ticker,
            )

        return {
            "messages": [result],
            "market_report": report,
            "market_analysis": market_analysis,
        }

    return market_analyst_node