import logging

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

logger = logging.getLogger(__name__)


MARKET_SYSTEM_PROMPT = """\
You are an expert Quantitative Market Analyst specializing in the NSE. Your task is to process the provided OHLCV price action, moving averages, momentum oscillators (RSI, MACD), Bollinger Bands, and institutional flow data, then output the analysis as a **strict, valid JSON object**.

CRITICAL RULES — Follow exactly:
1. Base every conclusion on specific values from the provided data. If a data point is not in the feed, do NOT invent it.
2. TREND CLASSIFICATION (deterministic):
   - STRONG_UPTREND: Price > 50 SMA > 200 SMA AND RSI > 50
   - WEAK_UPTREND: Price > 50 SMA but RSI between 40-50
   - RANGE_BOUND: Price between SMA 50 and SMA 200 with <5% spread
   - WEAK_DOWNTREND: Price < 50 SMA but RSI between 50-60
   - STRONG_DOWNTREND: Price < 50 SMA < 200 SMA AND RSI < 50
3. SUPPORT/RESISTANCE: Identify at least 2 support levels and at least 2 resistance levels. Use Bollinger bands (lower=first support, upper=first resistance), recent swing lows/highs, and moving averages (20 SMA, 50 SMA, 200 SMA). List from CLOSEST to furthest from current price. Report EXACT numbers. Example: `[2820, 2750, 2680]` where 2820 is the nearest support (just below price). Report as a JSON list of floats.
4. MOMENTUM STATE: RSI > 70 = OVERBOUGHT, RSI < 30 = OVERSOLD, else NEUTRAL. For MACD: histogram declining = weakening momentum even if RSI is neutral.
5. INSTITUTIONAL FLOW: Find volume data in the provided feed. If volume on up-days > volume on down-days by 50%+ → FII_BULLISH. If volume spikes >2x the 20-day average AND price drops → distribution / BEARISH. Always cite the specific volume values (e.g., "Volume: 12M vs 20d avg 5M") that inform your decision. If cumulative FII/DII data is available in the feed, prioritise that over inferred volume analysis.
6. CONFLICT RESOLUTION: When indicators disagree, priority order is: (1) Volume-confirmed breakout > (2) RSI divergence > (3) Moving average crossovers.
7. VERDICT: Synthesize ALL above. Do not default to NEUTRAL. If 3+ signals point one way, commit to BULLISH or BEARISH.

OUTPUT SCHEMA — use EXACTLY these field names. Do NOT rename, add, or omit any fields:
{
  "ticker": "<String>",
  "current_trend": "<String: 'STRONG_UPTREND' | 'WEAK_UPTREND' | 'RANGE_BOUND' | 'WEAK_DOWNTREND' | 'STRONG_DOWNTREND'>",
  "key_support": [<Float>, <Float>, ...],
  "key_resistance": [<Float>, <Float>, ...],
  "momentum_state": "<String: 'OVERSOLD' | 'OVERBOUGHT' | 'NEUTRAL'>",
  "institutional_flow_bias": "<String: 'FII_BULLISH' | 'DII_BULLISH' | 'MIXED' | 'BEARISH'>",
  "technical_verdict": "<String: 'BULLISH' | 'BEARISH' | 'NEUTRAL'>"
}

Do NOT provide conversational filler, introductions, or markdown outside of the JSON block.
After the JSON block you may optionally append a Markdown table.
"""


def create_market_analyst(llm):

    def market_analyst_node(state):
        import time as _time
        t0 = _time.time()
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        logger.info("[Market] START ticker=%s", ticker)
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

        try:
            result = chain.invoke(state["messages"])
            logger.info("[Market] LLM call completed (%.1fs)", _time.time() - t0)
        except Exception as exc:
            logger.error("[Market] FAILED after %.1fs: %s", _time.time() - t0, exc)
            return {
                "messages": state["messages"],
                "market_report": f"Market analysis failed: {exc}",
                "market_analysis": None,
            }

        report = ""
        market_analysis = None

        if len(result.tool_calls) == 0:
            report = result.content
            market_analysis = extract_and_validate(
                report,
                MarketAnalysis,
                ticker=ticker,
            )

        logger.info("[Market] DONE (%.1fs) ticker=%s verdict=%s",
                    _time.time() - t0, ticker,
                    market_analysis.get("technical_verdict") if market_analysis else "none")

        return {
            "messages": [result],
            "market_report": report,
            "market_analysis": market_analysis,
        }

    return market_analyst_node