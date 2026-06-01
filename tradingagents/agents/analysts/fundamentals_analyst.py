from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.schemas import (
    FundamentalsAnalysis,
    extract_and_validate,
)
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_insider_transactions,
    get_language_instruction,
)


FUNDAMENTALS_SYSTEM_PROMPT = """\
You are an expert Fundamental Analyst for the Indian stock market. Your task is to evaluate the provided financial statements and corporate metrics and output a **strict, valid JSON object**.

You must analyze the data objectively. Do **not** provide conversational filler, introductions, or markdown formatting outside of the JSON block.

Evaluation Criteria:
- Assess valuation (e.g., P/E relative to sector averages).
- Evaluate balance sheet health (e.g., Debt-to-Equity).
- Identify growth trajectories (e.g., EPS YoY growth).

Output Schema Requirement:
```json
{
  "ticker": "<String>",
  "valuation_score": "<Float between 1.0 (extremely undervalued) and 10.0 (extremely overvalued)>",
  "health_status": "<String: 'Robust' | 'Stable' | 'Vulnerable' | 'Distressed'>",
  "primary_strength": "<String: 1-sentence description referencing a specific metric>",
  "primary_weakness": "<String: 1-sentence description referencing a specific metric>",
  "overall_fundamental_verdict": "<String: 'BULLISH' | 'BEARISH' | 'NEUTRAL'>"
}
```

After the JSON block you may optionally append a Markdown table summarizing key financial metrics for human readability.
"""


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        instrument_context = build_instrument_context(ticker)

        tools = [
            get_fundamentals,
            get_balance_sheet,
            get_cashflow,
            get_income_statement,
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

        prompt = prompt.partial(system_message=FUNDAMENTALS_SYSTEM_PROMPT)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""
        fundamentals_analysis = None

        if len(result.tool_calls) == 0:
            report = result.content
            # Attempt structured extraction
            fundamentals_analysis = extract_and_validate(
                report,
                FundamentalsAnalysis,
                ticker=ticker,
            )

        return {
            "messages": [result],
            "fundamentals_report": report,
            "fundamentals_analysis": fundamentals_analysis,
        }

    return fundamentals_analyst_node