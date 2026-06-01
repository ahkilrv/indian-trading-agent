"""Analysis endpoints — run multi-agent analysis with WebSocket streaming."""

import asyncio
import uuid
import time
import threading
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, BackgroundTasks
from backend.models import AnalysisRequest, AnalysisResponse
from backend.ws import manager
from backend.db import save_analysis, get_analysis, get_analysis_history, update_analysis_pnl
from pydantic import BaseModel as PydanticBaseModel
from typing import Optional
from tradingagents.utils.ticker import normalize_ticker
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.agents import compile_report

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# In-memory task state
_tasks: dict[str, dict] = {}


def _run_analysis_sync(task_id: str, ticker: str, trade_date: str, config: dict, selected_analysts: list[str] = None):
    """Run the trading agent analysis in a background thread."""
    import asyncio
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.graph.propagation import Propagator
    from backend.stats_callback import StatsCallback

    if selected_analysts is None:
        selected_analysts = ["market", "social", "news", "fundamentals"]

    loop = asyncio.new_event_loop()

    start_time = time.time()
    _tasks[task_id]["status"] = "running"
    _tasks[task_id]["stopped"] = False
    stats = StatsCallback()

    def _should_stop() -> bool:
        return bool(_tasks.get(task_id, {}).get("stopped", False))

    try:
        ta = TradingAgentsGraph(
            selected_analysts=selected_analysts,
            debug=False,
            config=config,
            callbacks=[stats],
        )

        # Stream the graph execution
        propagator = Propagator(max_recur_limit=config.get("max_recur_limit", 100))
        init_state = propagator.create_initial_state(ticker, trade_date)
        stream_args = propagator.get_graph_args()

        prev_reports = {}
        chunk_count = 0

        for chunk in ta.graph.stream(init_state, **stream_args):
            chunk_count += 1
            # Check stop signal
            if _should_stop():
                print(f"[Analysis {task_id}] Stopped by user after {chunk_count} chunks", flush=True)
                loop.run_until_complete(manager.send_event(task_id, {
                    "type": "stopped",
                    "message": f"Analysis stopped after {chunk_count} chunks",
                }))
                _tasks[task_id]["status"] = "stopped"
                break
            # Heartbeat — let frontend know we're still alive
            last_message = ""
            if chunk.get("messages"):
                msg = chunk["messages"][-1]
                msg_type = type(msg).__name__
                content_preview = ""
                if hasattr(msg, "content") and msg.content:
                    content_preview = str(msg.content)[:80] if isinstance(msg.content, str) else "tool result"
                tool_calls = ""
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    tool_calls = f" (calling: {msg.tool_calls[0].get('name', '?')})"
                last_message = f"{msg_type}{tool_calls}: {content_preview}"
            print(f"[Analysis {task_id}] Chunk #{chunk_count} — {last_message}", flush=True)

            loop.run_until_complete(manager.send_event(task_id, {
                "type": "heartbeat",
                "chunk": chunk_count,
                "last_activity": last_message[:120],
            }))

            # Detect report updates
            for field in ["market_report", "sentiment_report", "news_report",
                          "fundamentals_report", "investment_plan",
                          "trader_investment_plan", "final_trade_decision"]:
                val = chunk.get(field)
                if val and val != prev_reports.get(field):
                    prev_reports[field] = val
                    print(f"[Analysis {task_id}] Report completed: {field}", flush=True)
                    loop.run_until_complete(manager.send_event(task_id, {
                        "type": "report",
                        "section": field,
                        "content": val,
                    }))

            # Detect structured payload updates (Pydantic-validated JSON from each agent)
            structured_payloads = [
                ("market_analysis",          "market"),
                ("fundamentals_analysis",    "fundamentals"),
                ("news_analysis",            "news"),
                ("social_sentiment",         "social"),
                ("bull_researcher_payload",  "bull"),
                ("bear_researcher_payload",  "bear"),
                ("research_manager_verdict", "research_manager"),
                ("trader_execution_plan",    "trader"),
                ("aggressive_debater_payload", "risk_aggressive"),
                ("conservative_debater_payload", "risk_conservative"),
                ("neutral_debater_payload",   "risk_neutral"),
                ("portfolio_manager_payload", "portfolio_manager"),
            ]
            for payload_field, agent in structured_payloads:
                val = chunk.get(payload_field)
                if val and val != prev_reports.get(payload_field):
                    prev_reports[payload_field] = val
                    # Convert Pydantic model to dict for JSON serialization
                    if hasattr(val, "model_dump"):
                        payload_dict = val.model_dump()
                    elif hasattr(val, "dict"):
                        payload_dict = val.dict()
                    else:
                        payload_dict = val
                    print(f"[Analysis {task_id}] Structured payload: {payload_field}", flush=True)
                    loop.run_until_complete(manager.send_event(task_id, {
                        "type": "structured_payload",
                        "agent": agent,
                        "field": payload_field,
                        "data": payload_dict,
                    }))

            # Detect debate updates
            invest_state = chunk.get("investment_debate_state")
            if invest_state:
                bull = invest_state.get("bull_history", "")
                bear = invest_state.get("bear_history", "")
                if bull and bull != prev_reports.get("bull_history"):
                    prev_reports["bull_history"] = bull
                    loop.run_until_complete(manager.send_event(task_id, {
                        "type": "debate", "side": "bull", "content": bull,
                    }))
                if bear and bear != prev_reports.get("bear_history"):
                    prev_reports["bear_history"] = bear
                    loop.run_until_complete(manager.send_event(task_id, {
                        "type": "debate", "side": "bear", "content": bear,
                    }))
                judge = invest_state.get("judge_decision", "")
                if judge and judge != prev_reports.get("judge_decision"):
                    prev_reports["judge_decision"] = judge
                    loop.run_until_complete(manager.send_event(task_id, {
                        "type": "report", "section": "investment_plan", "content": judge,
                    }))

            # Detect risk debate updates
            risk_state = chunk.get("risk_debate_state")
            if risk_state:
                for side in ["aggressive", "conservative", "neutral"]:
                    key = f"{side}_history"
                    val = risk_state.get(key, "")
                    if val and val != prev_reports.get(f"risk_{key}"):
                        prev_reports[f"risk_{key}"] = val
                        loop.run_until_complete(manager.send_event(task_id, {
                            "type": "risk_debate", "side": side, "content": val,
                        }))

        # Get final state
        final_state = chunk  # Last chunk is the final state
        signal = ta.process_signal(final_state.get("final_trade_decision", ""))

        duration = time.time() - start_time
        stats_summary = stats.summary()

        # Send final events
        loop.run_until_complete(manager.send_event(task_id, {
            "type": "signal", "decision": signal, "ticker": ticker,
        }))
        loop.run_until_complete(manager.send_event(task_id, {
            "type": "stats", **stats_summary,
        }))
        loop.run_until_complete(manager.send_event(task_id, {
            "type": "complete",
            "duration_seconds": round(duration, 1),
            "stats": stats_summary,
        }))

        # Save to DB
        invest_state = final_state.get("investment_debate_state", {})
        risk_state = final_state.get("risk_debate_state", {})

        result_data = {
            "ticker": ticker,
            "trade_date": trade_date,
            "signal": signal,
            "market_report": final_state.get("market_report"),
            "sentiment_report": final_state.get("sentiment_report"),
            "news_report": final_state.get("news_report"),
            "fundamentals_report": final_state.get("fundamentals_report"),
            "investment_plan": final_state.get("investment_plan"),
            "trader_investment_plan": final_state.get("trader_investment_plan"),
            "final_trade_decision": final_state.get("final_trade_decision"),
            "bull_history": invest_state.get("bull_history"),
            "bear_history": invest_state.get("bear_history"),
            "risk_aggressive_history": risk_state.get("aggressive_history"),
            "risk_conservative_history": risk_state.get("conservative_history"),
            "risk_neutral_history": risk_state.get("neutral_history"),
            "stats": stats_summary,
            "duration_seconds": round(duration, 1),
            # Structured Pydantic outputs
            "social_sentiment": final_state.get("social_sentiment"),
            "market_analysis": final_state.get("market_analysis"),
            "fundamentals_analysis": final_state.get("fundamentals_analysis"),
            "news_analysis": final_state.get("news_analysis"),
            "social_sentiment": final_state.get("social_sentiment"),
            "bull_researcher_payload": final_state.get("bull_researcher_payload"),
            "bear_researcher_payload": final_state.get("bear_researcher_payload"),
            "research_manager_verdict": final_state.get("research_manager_verdict"),
            "trader_execution_plan": final_state.get("trader_execution_plan"),
            "aggressive_debater_payload": final_state.get("aggressive_debater_payload"),
            "conservative_debater_payload": final_state.get("conservative_debater_payload"),
            "neutral_debater_payload": final_state.get("neutral_debater_payload"),
            "portfolio_manager_payload": final_state.get("portfolio_manager_payload"),
        }

        save_analysis(task_id, result_data)
        _tasks[task_id]["status"] = "completed"
        _tasks[task_id]["result"] = result_data

    except Exception as e:
        _tasks[task_id]["status"] = "error"
        _tasks[task_id]["error"] = str(e)
        loop.run_until_complete(manager.send_event(task_id, {
            "type": "error", "message": str(e),
        }))
    finally:
        loop.close()


@router.post("/run")
def run_analysis(req: AnalysisRequest):
    """Start a new analysis. Returns task_id for WebSocket streaming."""
    task_id = str(uuid.uuid4())[:8]
    ticker = normalize_ticker(req.ticker)

    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = req.max_debate_rounds
    config["max_risk_discuss_rounds"] = req.max_risk_discuss_rounds
    config["output_language"] = req.output_language

    _tasks[task_id] = {
        "status": "pending",
        "ticker": ticker,
        "trade_date": req.trade_date,
        "analysts": req.analysts,
    }

    thread = threading.Thread(
        target=_run_analysis_sync,
        args=(task_id, ticker, req.trade_date, config, req.analysts),
        daemon=True,
    )
    thread.start()

    return AnalysisResponse(
        task_id=task_id,
        status="started",
        ticker=ticker,
        trade_date=req.trade_date,
    )


@router.websocket("/ws/{task_id}")
async def analysis_websocket(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for streaming analysis progress."""
    await manager.connect(websocket, task_id)
    try:
        while True:
            # Keep alive — wait for client messages or disconnection
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)


@router.get("/{task_id}")
def get_analysis_result(task_id: str):
    """Get a completed analysis result."""
    # Check in-memory first
    if task_id in _tasks:
        task = _tasks[task_id]
        if task["status"] == "completed":
            return task.get("result", {})
        return {"task_id": task_id, "status": task["status"]}

    # Check DB
    result = get_analysis(task_id)
    if result:
        return result
    return {"error": "Analysis not found"}


@router.post("/{task_id}/stop")
def stop_analysis(task_id: str):
    """Stop a running analysis."""
    if task_id not in _tasks:
        return {"ok": False, "error": "Task not found"}
    task = _tasks[task_id]
    if task["status"] not in ("pending", "running"):
        return {"ok": False, "error": f"Task is already {task['status']}"}
    _tasks[task_id]["stopped"] = True
    _tasks[task_id]["status"] = "stopping"
    return {"ok": True, "task_id": task_id, "message": "Stop signal sent"}


class PnLUpdate(PydanticBaseModel):
    entry_price: float
    exit_price: float | None = None  # If None, trade is "open" — no exit yet
    reflect: bool = False  # If True, feed P&L to agent memory


@router.put("/{task_id}/pnl")
def update_pnl(task_id: str, data: PnLUpdate):
    """Update P&L for a completed analysis. Optionally feed to agent memory (reflect).

    If exit_price is None, trade is marked as 'open' (no exit yet).
    """
    analysis = get_analysis(task_id)
    if not analysis:
        return {"error": "Analysis not found"}

    # Open trade (entry only, no exit yet)
    if data.exit_price is None:
        update_analysis_pnl(task_id, data.entry_price, None, None, None, "open")
        return {
            "status": "updated",
            "pnl_status": "open",
            "message": "Trade marked as open. Update again with exit price when you close.",
        }

    pnl_amount = data.exit_price - data.entry_price
    pnl_pct = round((pnl_amount / data.entry_price) * 100, 2)
    pnl_status = "win" if pnl_amount > 0 else ("loss" if pnl_amount < 0 else "breakeven")

    # Flip for SELL/SHORT signals
    signal = (analysis.get("signal") or "").upper()
    if signal in ("SELL", "UNDERWEIGHT", "SHORT"):
        pnl_amount = -pnl_amount
        pnl_pct = -pnl_pct
        pnl_status = "win" if pnl_amount > 0 else ("loss" if pnl_amount < 0 else "breakeven")

    update_analysis_pnl(task_id, data.entry_price, data.exit_price, round(pnl_amount, 2), pnl_pct, pnl_status)

    reflection_result = None
    if data.reflect:
        reflection_result = _reflect_on_analysis(analysis, pnl_amount)

    return {
        "status": "updated",
        "pnl_pct": pnl_pct,
        "pnl_amount": round(pnl_amount, 2),
        "pnl_status": pnl_status,
        "reflection": reflection_result,
    }


def _reflect_on_analysis(analysis: dict, pnl_amount: float) -> dict:
    """Run reflection on a past analysis and save to agent memories."""
    try:
        from tradingagents.graph.reflection import Reflector
        from tradingagents.agents.utils.memory import FinancialSituationMemory
        from tradingagents.llm_clients import create_llm_client

        # Reconstruct state from DB
        state = {
            "market_report": analysis.get("market_report", ""),
            "sentiment_report": analysis.get("sentiment_report", ""),
            "news_report": analysis.get("news_report", ""),
            "fundamentals_report": analysis.get("fundamentals_report", ""),
            "investment_debate_state": {
                "bull_history": analysis.get("bull_history", ""),
                "bear_history": analysis.get("bear_history", ""),
                "judge_decision": analysis.get("investment_plan", ""),
            },
            "trader_investment_plan": analysis.get("trader_investment_plan", ""),
            "risk_debate_state": {
                "judge_decision": analysis.get("final_trade_decision", ""),
            },
        }

        # Skip if no reports
        if not state["market_report"] and not state["news_report"]:
            return {"error": "No reports available for reflection"}

        # Create LLM client
        quick_client = create_llm_client(
            provider=DEFAULT_CONFIG["llm_provider"],
            model=DEFAULT_CONFIG["quick_think_llm"],
        )
        quick_llm = quick_client.get_llm()

        reflector = Reflector(quick_llm)

        # Create memory instances (they auto-load from disk)
        bull_mem = FinancialSituationMemory("bull_memory", DEFAULT_CONFIG)
        bear_mem = FinancialSituationMemory("bear_memory", DEFAULT_CONFIG)
        trader_mem = FinancialSituationMemory("trader_memory", DEFAULT_CONFIG)
        judge_mem = FinancialSituationMemory("invest_judge_memory", DEFAULT_CONFIG)
        pm_mem = FinancialSituationMemory("portfolio_manager_memory", DEFAULT_CONFIG)

        # Run reflection — each adds to memory + auto-saves to disk
        reflector.reflect_bull_researcher(state, pnl_amount, bull_mem)
        reflector.reflect_bear_researcher(state, pnl_amount, bear_mem)
        reflector.reflect_trader(state, pnl_amount, trader_mem)
        reflector.reflect_invest_judge(state, pnl_amount, judge_mem)
        reflector.reflect_portfolio_manager(state, pnl_amount, pm_mem)

        return {
            "ok": True,
            "memories_updated": {
                "bull": bull_mem.count(),
                "bear": bear_mem.count(),
                "trader": trader_mem.count(),
                "judge": judge_mem.count(),
                "portfolio_manager": pm_mem.count(),
            },
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/memory/stats")
def get_memory_stats():
    """Get count of stored memories per agent."""
    try:
        from tradingagents.agents.utils.memory import FinancialSituationMemory
        memories = {
            "bull_memory": FinancialSituationMemory("bull_memory", DEFAULT_CONFIG).count(),
            "bear_memory": FinancialSituationMemory("bear_memory", DEFAULT_CONFIG).count(),
            "trader_memory": FinancialSituationMemory("trader_memory", DEFAULT_CONFIG).count(),
            "invest_judge_memory": FinancialSituationMemory("invest_judge_memory", DEFAULT_CONFIG).count(),
            "portfolio_manager_memory": FinancialSituationMemory("portfolio_manager_memory", DEFAULT_CONFIG).count(),
        }
        return {
            "memories": memories,
            "total": sum(memories.values()),
        }
    except Exception as e:
        return {"error": str(e)}


class ChatRequest(PydanticBaseModel):
    message: str
    ticker: str
    trade_date: str
    signal: str
    reports: dict = {}
    debates: dict = {}
    risk_debates: dict = {}
    stats: Optional[dict] = None
    history: list[dict] = []
    duration: Optional[float] = None


class PdfExportRequest(PydanticBaseModel):
    ticker: str
    trade_date: str
    signal: Optional[str] = None
    reports: dict = {}
    debates: dict = {}
    risk_debates: dict = {}
    stats: Optional[dict] = None
    duration: Optional[float] = None


@router.post("/chat")
def analysis_chat(req: ChatRequest):
    """Answer a user question using the full analysis context.

    Builds a system prompt from all reports, debates, signal and stats,
    then calls the configured LLM (quick-think model) and returns the response.
    """
    # Build the analysis context
    context_parts = []

    # Signal
    context_parts.append(f"## Final Verdict\n**Signal:** {req.signal}")
    context_parts.append(f"**Ticker:** {req.ticker}")
    context_parts.append(f"**Analysis Date:** {req.trade_date}")
    if req.duration:
        context_parts.append(f"**Duration:** {req.duration:.0f}s")

    # Stats
    if req.stats:
        context_parts.append(f"\n## Stats\n- LLM calls: {req.stats.get('llm_calls', '—')}")
        context_parts.append(f"- Total tokens: {req.stats.get('total_tokens', '—')}")
        context_parts.append(f"- Cost: ${req.stats.get('cost_usd', '—')} (₹{req.stats.get('cost_inr', '—')})")

    # Reports
    report_labels = {
        "market_report": "Market Report",
        "sentiment_report": "Sentiment/Social Media Report",
        "news_report": "News Analysis Report",
        "fundamentals_report": "Fundamentals Report",
        "investment_plan": "Investment Plan (Judge Decision)",
        "trader_investment_plan": "Trader's Investment Plan",
        "final_trade_decision": "Final Trade Decision",
    }
    for key, label in report_labels.items():
        if req.reports.get(key):
            context_parts.append(f"\n## {label}\n{req.reports[key]}")

    # Debates
    for side, label in [("bull", "Bull Case"), ("bear", "Bear Case")]:
        if req.debates.get(side):
            context_parts.append(f"\n## {label}\n{req.debates[side]}")

    # Risk debates
    risk_labels = {"aggressive": "Aggressive", "conservative": "Conservative", "neutral": "Neutral"}
    for side, label in risk_labels.items():
        if req.risk_debates.get(side):
            context_parts.append(f"\n## Risk Debate — {label}\n{req.risk_debates[side]}")

    system_prompt = (
        "You are an expert Indian stock market analyst assistant. Below is the complete "
        "multi-agent analysis output for a stock. Answer the user's questions using ONLY "
        "the context provided. If the answer isn't in the context, say so plainly — do not "
        "make up information. Be specific, cite which report or section your answer comes from, "
        "and explain your reasoning clearly.\n\n"
        "--- ANALYSIS CONTEXT ---\n"
        + "\n".join(context_parts)
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in req.history:
        role = msg.get("role", "user")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": msg.get("content", "")})
    messages.append({"role": "user", "content": req.message})

    try:
        quick_client = create_llm_client(
            provider=DEFAULT_CONFIG["llm_provider"],
            model=DEFAULT_CONFIG["quick_think_llm"],
            base_url=DEFAULT_CONFIG.get("backend_url"),
        )
        quick_llm = quick_client.get_llm()
        response = quick_llm.invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        # Normalize if content is a list (e.g., DeepSeek thinking blocks)
        from tradingagents.llm_clients.base_client import normalize_content
        normalize_content(response)
        return {"reply": response.content}
    except Exception as e:
        import traceback
        traceback.print_exc()
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/pdf-export")
def export_pdf(req: PdfExportRequest):
    """Generate a compiled PDF report using the report compiler agent."""
    try:
        # Create LLM client for the compiler
        quick_client = create_llm_client(
            provider=DEFAULT_CONFIG["llm_provider"],
            model=DEFAULT_CONFIG["quick_think_llm"],
            base_url=DEFAULT_CONFIG.get("backend_url"),
        )
        quick_llm = quick_client.get_llm()

        # Compile the HTML report via LLM
        html_content = compile_report(
            llm=quick_llm,
            ticker=req.ticker,
            trade_date=req.trade_date,
            signal=req.signal or "",
            duration_str=f"{req.duration:.0f}s" if req.duration else "—",
            stats=req.stats or {},
            reports=req.reports or {},
            debates=req.debates or {},
            risk_debates=req.risk_debates or {},
        )

        # Try weasyprint first, fall back to returning HTML
        try:
            from weasyprint import HTML
            import io

            pdf_buffer = io.BytesIO()
            HTML(string=html_content).write_pdf(pdf_buffer)
            pdf_buffer.seek(0)

            from fastapi.responses import StreamingResponse
            return StreamingResponse(
                pdf_buffer,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename={req.ticker}_analysis_{req.trade_date}.pdf"
                },
            )
        except ImportError:
            # Fallback: return HTML for browser print
            from fastapi.responses import HTMLResponse
            return HTMLResponse(
                content=html_content,
                headers={
                    "Content-Disposition": f"inline; filename={req.ticker}_analysis_{req.trade_date}.html"
                },
            )

    except Exception as e:
        from fastapi.responses import JSONResponse
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@router.get("/history/list")
def list_analysis_history(limit: int = 50, offset: int = 0):
    """List past analyses."""
    return get_analysis_history(limit, offset)
