"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { runAnalysis, stopAnalysis, connectAnalysisWS } from "@/lib/api";
import type { WSEvent } from "@/lib/types";

interface AnalysisOptions {
  analysts?: string[];
  max_debate_rounds?: number;
  max_risk_discuss_rounds?: number;
  output_language?: string;
}

interface AnalysisStats {
  llm_calls: number;
  tool_calls: number;
  tokens_in: number;
  tokens_out: number;
  total_tokens: number;
  cost_usd: number;
  cost_inr: number;
  per_model?: Record<string, { input: number; output: number }>;
}

interface AnalysisState {
  taskId: string | null;
  ticker: string;
  tradeDate: string;
  status: "idle" | "running" | "completed" | "error" | "stopping";
  reports: Record<string, string>;
  debates: { bull: string; bear: string };
  riskDebates: { aggressive: string; conservative: string; neutral: string };
  signal: string | null;
  error: string | null;
  duration: number | null;
  ws: WebSocket | null;
  heartbeat: string;
  lastUpdateAt: number;
  startedAt: number;
  stats: AnalysisStats | null;
  structuredPayloads: Record<string, any>;
  activeAgent: string;
  chunkCount: number;
  toolName: string;

  start: (ticker: string, tradeDate: string, options?: AnalysisOptions) => Promise<void>;
  stop: () => void;
  reset: () => void;
}

export const AGENT_TIMEOUT_MS = 60_000;

const TOOL_AGENT_MAP: Record<string, string> = {
  get_stock_data: "Market Analyst",
  get_indicators: "Market Analyst",
  get_trends: "Social Analyst",
  get_youtube_sentiment: "Social Analyst",
  get_forums_sentiment: "Social Analyst",
  get_news: "Social/News Analyst",
  get_global_news: "News Analyst",
  get_serp_news: "News Analyst",
  get_ticker_news: "News Analyst",
  get_fundamentals: "Fundamentals Analyst",
  get_balance_sheet: "Fundamentals Analyst",
  get_cashflow: "Fundamentals Analyst",
  get_income_statement: "Fundamentals Analyst",
};

const REPORT_AGENT_MAP: Record<string, string> = {
  market_report: "Market Analyst",
  sentiment_report: "Social Analyst",
  news_report: "News Analyst",
  fundamentals_report: "Fundamentals Analyst",
  investment_plan: "Research Manager",
  trader_investment_plan: "Trader",
  final_trade_decision: "Portfolio Manager",
};

function parseAgent(hb: string, reports: Record<string, string>): { agent: string; tool: string } {
  let tool = "";
  const m = hb.match(/calling:\s*(\w+)/);
  if (m) tool = m[1];
  if (hb.startsWith("ToolMessage")) tool = "";

  let agent = "";
  if (tool && TOOL_AGENT_MAP[tool]) {
    agent = TOOL_AGENT_MAP[tool];
  } else {
    for (const [key, name] of Object.entries(REPORT_AGENT_MAP)) {
      if (!reports[key]) { agent = name; break; }
    }
  }
  return { agent, tool };
}

export const useAnalysisStore = create<AnalysisState>()(
  persist(
    (set, get) => ({
      taskId: null,
      ticker: "",
      tradeDate: "",
      status: "idle",
      reports: {},
      debates: { bull: "", bear: "" },
      riskDebates: { aggressive: "", conservative: "", neutral: "" },
      signal: null,
      error: null,
      duration: null,
      ws: null,
      heartbeat: "",
      lastUpdateAt: 0,
      startedAt: 0,
      stats: null,
      structuredPayloads: {},
      activeAgent: "",
      chunkCount: 0,
      toolName: "",

      start: async (ticker, tradeDate, options = {}) => {
        const existingWs = get().ws;
        if (existingWs) try { existingWs.close(); } catch {}

        set({
          ticker,
          tradeDate,
          status: "running",
          reports: {},
          debates: { bull: "", bear: "" },
          riskDebates: { aggressive: "", conservative: "", neutral: "" },
          signal: null, error: null, duration: null, ws: null,
          heartbeat: "Initializing...",
          lastUpdateAt: Date.now(), startedAt: Date.now(),
          stats: null, structuredPayloads: {},
          activeAgent: "", chunkCount: 0, toolName: "",
        });

        try {
          const result: any = await runAnalysis({
            ticker, trade_date: tradeDate,
            analysts: options.analysts,
            max_debate_rounds: options.max_debate_rounds,
            max_risk_discuss_rounds: options.max_risk_discuss_rounds,
            output_language: options.output_language,
          });
          const taskId = result.task_id;
          let stopped = false;

          const ws = connectAnalysisWS(taskId, (event: any) => {
            if (stopped) return;
            const s = get();
            switch (event.type) {
              case "heartbeat": {
                const { agent, tool } = parseAgent(event.last_activity || "", s.reports);
                set({ chunkCount: event.chunk || 0, toolName: tool, activeAgent: agent, heartbeat: event.last_activity || "", lastUpdateAt: Date.now() });
                break;
              }
              case "report":
                set({ reports: { ...s.reports, [event.section!]: event.content! }, lastUpdateAt: Date.now() });
                break;
              case "debate":
                set({ debates: { ...s.debates, [event.side!]: event.content! }, lastUpdateAt: Date.now() });
                break;
              case "risk_debate":
                set({ riskDebates: { ...s.riskDebates, [event.side!]: event.content! }, lastUpdateAt: Date.now() });
                break;
              case "signal":
                set({ signal: event.decision!, lastUpdateAt: Date.now() });
                break;
              case "stats":
                set({ stats: { llm_calls: event.llm_calls || 0, tool_calls: event.tool_calls || 0, tokens_in: event.tokens_in || 0, tokens_out: event.tokens_out || 0, total_tokens: event.total_tokens || 0, cost_usd: event.cost_usd || 0, cost_inr: event.cost_inr || 0, per_model: event.per_model }, lastUpdateAt: Date.now() });
                break;
              case "structured_payload":
                if (event.agent && event.data) set({ structuredPayloads: { ...s.structuredPayloads, [event.agent]: event.data }, lastUpdateAt: Date.now() });
                break;
              case "complete":
                stopped = true; ws.close();
                set({ status: "completed", duration: event.duration_seconds ?? null, ws: null, heartbeat: "Complete", stats: event.stats ? { llm_calls: event.stats.llm_calls || 0, tool_calls: event.stats.tool_calls || 0, tokens_in: event.stats.tokens_in || 0, tokens_out: event.stats.tokens_out || 0, total_tokens: event.stats.total_tokens || 0, cost_usd: event.stats.cost_usd || 0, cost_inr: event.stats.cost_inr || 0, per_model: event.stats.per_model } : get().stats });
                break;
              case "error":
                stopped = true; ws.close();
                set({ status: "error", error: event.message ?? "Unknown error", ws: null });
                break;
              case "stopped":
                stopped = true; ws.close();
                set({ status: "completed", ws: null, heartbeat: "Stopped by user" });
                break;
            }
          });

          if (stopped) try { ws.close(); } catch {}
          else set({ taskId, ws });
        } catch (e: any) {
          set({ status: "error", error: e.message });
        }
      },

      stop: () => {
        const { taskId, ws } = get();
        set({ status: "idle", taskId: null, ws: null, heartbeat: "Stopped by user", lastUpdateAt: 0, startedAt: 0, activeAgent: "", chunkCount: 0, toolName: "" });
        if (ws) try { ws.close(); } catch {}
        if (taskId) stopAnalysis(taskId).catch(() => {});
      },

      reset: () => {
        const ws = get().ws;
        if (ws) try { ws.close(); } catch {}
        set({ taskId: null, ticker: "", tradeDate: "", status: "idle", reports: {}, debates: { bull: "", bear: "" }, riskDebates: { aggressive: "", conservative: "", neutral: "" }, signal: null, error: null, duration: null, ws: null, heartbeat: "", lastUpdateAt: 0, startedAt: 0, stats: null, structuredPayloads: {}, activeAgent: "", chunkCount: 0, toolName: "" });
      },
    }),
    {
      name: "analysis-store",
      partialize: (state) => ({
        taskId: state.taskId, ticker: state.ticker, tradeDate: state.tradeDate,
        status: state.status, reports: state.reports, debates: state.debates,
        riskDebates: state.riskDebates, signal: state.signal, duration: state.duration,
        stats: state.stats, structuredPayloads: state.structuredPayloads,
      }),
      onRehydrateStorage: () => (s, err) => {
        if (err || !s) return;
        if (s.status === "running" && !s.taskId) {
          useAnalysisStore.setState({ status: "idle", taskId: null, ws: null, heartbeat: "", startedAt: 0 });
        }
      },
    }
  )
);
