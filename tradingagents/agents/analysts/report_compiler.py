"""Report Compiler — renders all research outputs into HTML faithfully without truncation or LLM reinterpretation."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from tradingagents.agents.analysts.schemas import format_analysis_for_prompt


def _md_to_html(text: str) -> str:
    """Convert basic markdown to HTML. Preserves all content faithfully."""
    if not text:
        return ""
    lines = text.split("\n")
    html_parts = []
    in_code = False
    code_buffer = []
    for line in lines:
        # Code block
        if line.strip().startswith("```"):
            if in_code:
                html_parts.append(f"<pre style=\"background:#f3f4f6;padding:12px;border-radius:6px;overflow-x:auto;font-size:11px;\">{''.join(code_buffer)}</pre>")
                code_buffer = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            code_buffer.append(escaped + "\n")
            continue

        stripped = line.strip()

        # Headers
        h_match = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if h_match:
            level = len(h_match.group(1))
            content = _inline_md(h_match.group(2))
            html_parts.append(f"<h{level} style=\"color:#111827;margin:16px 0 8px 0;\">{content}</h{level}>")
            continue

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            html_parts.append("<hr style=\"border:none;border-top:1px solid #e5e7eb;margin:16px 0;\">")
            continue

        # Unordered list
        if stripped.startswith("- ") or stripped.startswith("* "):
            content = _inline_md(stripped[2:])
            html_parts.append(f"<li style=\"margin:2px 0;\">{content}</li>")
            continue

        # Ordered list
        ol_match = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if ol_match:
            content = _inline_md(ol_match.group(1))
            html_parts.append(f"<li style=\"margin:2px 0;\">{content}</li>")
            continue

        # Table row
        if "|" in stripped and stripped.startswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            is_header = all(re.match(r"^[-:]+$", c) for c in cells if c)
            if is_header:
                continue
            html_parts.append(f"<tr>{''.join(f'<td style=\"border:1px solid #d1d5db;padding:6px 10px;font-size:11px;\">{_inline_md(c)}</td>' for c in cells)}</tr>")
            continue

        # Paragraph
        if stripped == "":
            html_parts.append("</p><p style=\"margin:8px 0;line-height:1.6;\">")
        else:
            content = _inline_md(stripped)
            if html_parts and html_parts[-1].startswith("<p"):
                html_parts.append(content + " ")
            else:
                html_parts.append(f"<p style=\"margin:8px 0;line-height:1.6;\">{content}")

    return "".join(html_parts)


def _inline_md(text: str) -> str:
    """Convert inline markdown formatting (bold, italic, code, links)."""
    # Code
    text = re.sub(r"`([^`]+)`", r"<code style=\"background:#f3f4f6;padding:1px 4px;border-radius:3px;font-size:11px;\">\1</code>", text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Links
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" style="color:#2563eb;">\1</a>', text)
    return text


def compile_report(
    llm=None,
    ticker: str = "",
    trade_date: str = "",
    signal: str = "",
    duration_str: str = "",
    stats: dict | None = None,
    reports: dict | None = None,
    debates: dict | None = None,
    risk_debates: dict | None = None,
    *,
    market_analysis: Optional[dict[str, Any]] = None,
    fundamentals_analysis: Optional[dict[str, Any]] = None,
    news_analysis: Optional[dict[str, Any]] = None,
    social_sentiment: Optional[dict[str, Any]] = None,
) -> str:
    """Render all analysis reports into a self-contained HTML document.

    Faithfully reproduces every report, debate and analysis section without
    truncation or LLM reinterpretation. Uses direct markdown-to-HTML conversion.
    """
    stats = stats or {}
    reports = reports or {}
    debates = debates or {}
    risk_debates = risk_debates or {}

    cost_usd_raw = stats.get("cost_usd", 0)
    cost_inr_raw = stats.get("cost_inr", 0)
    try:
        cost_usd_val = round(float(cost_usd_raw), 4)
    except (ValueError, TypeError):
        cost_usd_val = 0
    try:
        cost_inr_val = round(float(cost_inr_raw), 2)
    except (ValueError, TypeError):
        cost_inr_val = 0

    signal_lower = (signal or "").lower()
    if "buy" in signal_lower or "bull" in signal_lower or "strong" in signal_lower:
        signal_color = "#16a34a"
        signal_bg = "#f0fdf4"
    elif "sell" in signal_lower or "bear" in signal_lower or "short" in signal_lower:
        signal_color = "#dc2626"
        signal_bg = "#fef2f2"
    else:
        signal_color = "#f59e0b"
        signal_bg = "#fffbeb"

    sections_html = []

    # Structured analyst scorecards
    structured = format_analysis_for_prompt(
        market_analysis=market_analysis,
        fundamentals_analysis=fundamentals_analysis,
        news_analysis=news_analysis,
        social_sentiment=social_sentiment,
    )
    if structured:
        sections_html.append(f"""<div style="background:{signal_bg};border:1px solid {signal_color}33;border-radius:8px;padding:16px;margin:16px 0;">
  <h2 style="color:{signal_color};margin:0 0 8px 0;">Structured Analyst Scorecards</h2>
  <div style="font-size:12px;line-height:1.6;">{_md_to_html(structured)}</div>
</div>""")

    # Report sections — faithful markdown rendering, no truncation
    report_sections = [
        ("Market & Technical Report", reports.get("market_report")),
        ("Sentiment & Social Media Report", reports.get("sentiment_report")),
        ("News Report", reports.get("news_report")),
        ("Fundamentals Report", reports.get("fundamentals_report")),
        ("Investment Plan — Research Manager", reports.get("investment_plan")),
        ("Trader Execution Plan", reports.get("trader_investment_plan")),
        ("Final Trade Decision", reports.get("final_trade_decision")),
    ]
    for label, content in report_sections:
        if not content:
            continue
        sections_html.append(f"""<div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin:12px 0;">
  <h2 style="color:#2563eb;margin:0 0 8px 0;font-size:16px;">{label}</h2>
  <div style="font-size:12px;line-height:1.6;">{_md_to_html(content)}</div>
</div>""")

    # Bull vs Bear debate
    bull = debates.get("bull", "")
    bear = debates.get("bear", "")
    if bull or bear:
        cols = ""
        if bull:
            cols += f"""<td style="width:50%;vertical-align:top;background:#f0fdf4;padding:12px;border-radius:6px;">
      <h3 style="color:#16a34a;margin:0 0 8px 0;">Bull Case</h3>
      <div style="font-size:12px;line-height:1.6;">{_md_to_html(bull)}</div>
    </td>"""
        if bear:
            cols += f"""<td style="width:50%;vertical-align:top;background:#fef2f2;padding:12px;border-radius:6px;">
      <h3 style="color:#dc2626;margin:0 0 8px 0;">Bear Case</h3>
      <div style="font-size:12px;line-height:1.6;">{_md_to_html(bear)}</div>
    </td>"""
        sections_html.append(f"""<div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin:12px 0;">
  <h2 style="color:#111827;margin:0 0 12px 0;font-size:16px;">Bull vs Bear Debate</h2>
  <table width="100%" cellspacing="8"><tr>{cols}</tr></table>
</div>""")

    # Risk debate
    risk_labels = [
        ("Aggressive Risk Profile", risk_debates.get("aggressive"), "#7c3aed", "#f5f3ff"),
        ("Conservative Risk Profile", risk_debates.get("conservative"), "#059669", "#ecfdf5"),
        ("Neutral Risk Profile", risk_debates.get("neutral"), "#f59e0b", "#fffbeb"),
    ]
    for label, content, color, bg in risk_labels:
        if not content:
            continue
        sections_html.append(f"""<div style="background:{bg};border:1px solid {color}33;border-radius:8px;padding:12px;margin:8px 0;">
  <h3 style="color:{color};margin:0 0 6px 0;font-size:14px;">{label}</h3>
  <div style="font-size:12px;line-height:1.6;">{_md_to_html(content)}</div>
</div>""")

    body = "\n".join(sections_html)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Trading Analysis Report — {ticker}</title>
</head>
<body style="font-family:Arial,Helvetica,sans-serif;background:#f9fafb;margin:0;padding:20px;color:#1f2937;">

<div style="max-width:780px;margin:0 auto;">

  <!-- Accent bar -->
  <div style="height:6px;background:linear-gradient(90deg,#2563eb,#7c3aed,#16a34a);border-radius:6px 6px 0 0;"></div>

  <!-- Header -->
  <div style="background:#ffffff;border:1px solid #e5e7eb;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
    <div style="font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Trading Analysis Report</div>
    <h1 style="font-size:28px;margin:0;">{ticker}</h1>
    <div style="color:#6b7280;font-size:13px;margin-top:4px;">
      Analysis Date: {trade_date} &middot; Duration: {duration_str}
    </div>
  </div>

  <!-- Signal badge -->
  <div style="background:{signal_bg};border:1px solid {signal_color}33;border-radius:8px;padding:16px;text-align:center;margin:12px 0;">
    <span style="background:{signal_color};color:#ffffff;padding:6px 20px;border-radius:20px;font-weight:bold;font-size:14px;">{signal or "N/A"}</span>
  </div>

  <!-- Stats bar -->
  <div style="background:#f3f4f6;border-radius:8px;padding:12px 16px;margin:12px 0;display:flex;gap:16px;flex-wrap:wrap;font-size:11px;color:#4b5563;">
    <span><strong>LLM Calls:</strong> {stats.get("llm_calls", 0)}</span>
    <span><strong>Tool Calls:</strong> {stats.get("tool_calls", 0)}</span>
    <span><strong>Tokens:</strong> {stats.get("total_tokens", 0)}</span>
    <span><strong>Cost:</strong> ${cost_usd_val} / ₹{cost_inr_val}</span>
  </div>

  <!-- Report body -->
  {body}

  <!-- Footer -->
  <div style="text-align:center;font-size:10px;color:#9ca3af;margin-top:24px;padding-top:16px;border-top:1px solid #e5e7eb;">
    Generated by Indian Trading Agent &middot; {datetime.now().strftime("%Y-%m-%d %H:%M")}
  </div>

</div>

</body>
</html>"""

    return html
