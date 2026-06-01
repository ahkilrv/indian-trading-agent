"""Structured debug logging for the agent pipeline.

Enabled via environment variable: DEBUG_ANALYSIS=true

Provides timing, LLM call tracking, and tool call tracking for
debugging hung or slow analyses.
"""

from __future__ import annotations

import logging
import os
import time
from functools import wraps
from typing import Any, Callable, Optional

# Module-level logger
logger = logging.getLogger("analysis.debug")

_DEBUG_ENABLED = os.environ.get("DEBUG_ANALYSIS", "").lower() in ("1", "true", "yes")

# ── In-memory log buffer for the debug API ────────────────────────
_MAX_LOG_LINES = 200
_log_buffer: list[tuple[float, str, str]] = []  # (timestamp, agent, message)


def _buffer(agent: str, message: str):
    if not _DEBUG_ENABLED:
        return
    entry = (time.time(), agent, message)
    _log_buffer.append(entry)
    if len(_log_buffer) > _MAX_LOG_LINES:
        _log_buffer.pop(0)
    logger.info("[%s] %s", agent, message)


def get_log_buffer(since: float = 0) -> list[dict]:
    """Return recent log lines (optionally filtered by timestamp)."""
    return [
        {"time": t, "agent": a, "message": m}
        for t, a, m in _log_buffer
        if t >= since
    ]


def clear_log_buffer():
    _log_buffer.clear()


# ── Agent-level timing decorator ──────────────────────────────────

def log_agent(agent_name: str):
    """Decorator for agent node functions. Logs entry, exit, duration, and errors."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(state: dict, *args: Any, **kwargs: Any) -> Any:
            ticker = state.get("company_of_interest", state.get("ticker", "?"))
            t0 = time.time()
            _buffer(agent_name, f"START ticker={ticker}")
            try:
                result = fn(state, *args, **kwargs)
                elapsed = time.time() - t0
                _buffer(agent_name, f"DONE ({elapsed:.1f}s) ticker={ticker}")
                return result
            except Exception as exc:
                elapsed = time.time() - t0
                _buffer(agent_name, f"ERROR ({elapsed:.1f}s) ticker={ticker} — {exc}")
                raise
        return wrapper
    return decorator


# ── LLM call tracking ────────────────────────────────────────────

_tool_call_id = 0


def log_llm_call(agent: str, model: str, prompt_len: int, duration: float, response_len: int = 0, tool_calls: int = 0):
    """Log an LLM call with size and timing."""
    _buffer(agent, f"LLM model={model} prompt={prompt_len}chars response={response_len}chars "
            f"tools={tool_calls} duration={duration:.1f}s")


def log_tool_call(agent: str, tool_name: str, arg_len: int, duration: float, result_len: int = 0, error: Optional[str] = None):
    """Log a tool call with size and timing."""
    status = f"ERROR: {error}" if error else "OK"
    _buffer(agent, f"TOOL {tool_name} args={arg_len}chars result={result_len}chars "
            f"duration={duration:.1f}s {status}")


def log_agent_step(agent: str, message: str):
    """Log a general agent step."""
    _buffer(agent, message)
