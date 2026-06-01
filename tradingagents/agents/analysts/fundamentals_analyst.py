import logging

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.schemas import (
    FundamentalsAnalysis,
    extract_and_validate,
)

logger = logging.getLogger(__name__)
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
You are an expert Fundamental Analyst for the Indian stock market. Your task is to evaluate the provided financial statements and corporate metrics, then output a **strict, valid JSON object**.

CRITICAL RULES:
1. Base every conclusion on specific numeric metrics from the provided data. Reference exact values.
2. VALUATION SCORE (integer 1-10, whole numbers only — do NOT use decimals): 1 = deeply undervalued, 10 = extremely overvalued. Must be SECTOR-RELATIVE. State the sector benchmark: e.g., "PE 18 vs IT sector avg 24 → undervalued." For Indian stocks, also check: P/B < 3 for financials, EV/EBITDA < 15 for industrials. Round to nearest whole number.
3. HEALTH STATUS (deterministic):
   - Robust: Debt/Equity < 1.0 AND Current Ratio > 1.5 AND positive FCF
   - Stable: Debt/Equity < 2.0 AND Current Ratio > 1.0
   - Vulnerable: Debt/Equity > 2.0 OR Current Ratio < 1.0 OR negative EPS
   - Distressed: Debt/Equity > 3.0 AND negative FCF AND negative EPS
4. INDIAN-SPECIFIC CHECKS: If promoter holding % is available, note concentrated (>50%) or diluted (<30%) ownership. High promoter holding = alignment, low = governance risk. Note delivery % if available — high delivery = genuine buying interest.
5. STRENGTH/WEAKNESS: Each must reference a SPECIFIC metric with its value. Example: "Revenue grew 12% YoY to ₹15,200Cr" NOT "Good revenue growth."
6. VERDICT: Do not default to NEUTRAL. If at least 2 of 3 (valuation, balance sheet, growth) point one direction, commit to BULLISH or BEARISH.

OUTPUT SCHEMA — use EXACTLY these field names. Do NOT rename, add, or omit any fields:
{
  "ticker": "<String>",
  "valuation_score": "<Integer 1-10 — whole number only>",
  "health_status": "<String: 'Robust' | 'Stable' | 'Vulnerable' | 'Distressed'>",
  "primary_strength": "<String: 1-sentence description referencing a specific metric>",
  "primary_weakness": "<String: 1-sentence description referencing a specific metric>",
  "overall_fundamental_verdict": "<String: 'BULLISH' | 'BEARISH' | 'NEUTRAL'>"
}

Do NOT provide conversational filler, introductions, or markdown outside of the JSON block.
After the JSON block you may optionally append a Markdown table.
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

        try:
            result = chain.invoke(state["messages"])
        except Exception as exc:
            logger.error("[Fundamentals] FAILED: %s", exc)
            return {
                "messages": state["messages"],
                "fundamentals_report": f"Fundamentals analysis failed: {exc}",
                "fundamentals_analysis": None,
            }

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