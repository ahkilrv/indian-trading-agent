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
  status: "idle" | "running" | "completed" | "error";
  reports: Record<string, string>;
  debates: { bull: string; bear: string };
  riskDebates: { aggressive: string; conservative: string; neutral: string };
  signal: string | null;
  error: string | null;
  duration: number | null;
  ws: WebSocket | null;
  heartbeat: string;
  lastUpdateAt: number;
  stats: AnalysisStats | null;
  structuredPayloads: Record<string, any>;

  start: (ticker: string, tradeDate: string, options?: AnalysisOptions) => Promise<void>;
  stop: () => Promise<void>;
  reset: () => void;
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
      stats: null,
      structuredPayloads: {},

      start: async (ticker: string, tradeDate: string, options: AnalysisOptions = {}) => {
    // Close existing WS if any
    const existingWs = get().ws;
    if (existingWs) {
      try { existingWs.close(); } catch {}
    }

    set({
      taskId: null,
      ticker,
      tradeDate,
      status: "running",
      reports: {},
      debates: { bull: "", bear: "" },
      riskDebates: { aggressive: "", conservative: "", neutral: "" },
      signal: null,
      error: null,
      duration: null,
      ws: null,
      heartbeat: "Initializing pipeline...",
      lastUpdateAt: Date.now(),
      stats: null,
      structuredPayloads: {},
    });

    try {
      const result: any = await runAnalysis({
        ticker,
        trade_date: tradeDate,
        analysts: options.analysts,
        max_debate_rounds: options.max_debate_rounds,
        max_risk_discuss_rounds: options.max_risk_discuss_rounds,
        output_language: options.output_language,
      });
      const taskId = result.task_id;

      const ws = connectAnalysisWS(taskId, (event: any) => {
        const state = get();
        switch (event.type) {
          case "heartbeat":
            set({ heartbeat: event.last_activity || `Processing chunk #${event.chunk}`, lastUpdateAt: Date.now() });
            break;
          case "report":
            set({ reports: { ...state.reports, [event.section!]: event.content! }, lastUpdateAt: Date.now() });
            break;
          case "debate":
            set({ debates: { ...state.debates, [event.side!]: event.content! }, lastUpdateAt: Date.now() });
            break;
          case "risk_debate":
            set({ riskDebates: { ...state.riskDebates, [event.side!]: event.content! }, lastUpdateAt: Date.now() });
            break;
          case "signal":
            set({ signal: event.decision!, lastUpdateAt: Date.now() });
            break;
          case "stats":
            set({
              stats: {
                llm_calls: event.llm_calls || 0,
                tool_calls: event.tool_calls || 0,
                tokens_in: event.tokens_in || 0,
                tokens_out: event.tokens_out || 0,
                total_tokens: event.total_tokens || 0,
                cost_usd: event.cost_usd || 0,
                cost_inr: event.cost_inr || 0,
                per_model: event.per_model,
              },
              lastUpdateAt: Date.now(),
            });
            break;
          case "structured_payload":
            if (event.agent && event.data) {
              set({
                structuredPayloads: { ...state.structuredPayloads, [event.agent]: event.data },
                lastUpdateAt: Date.now(),
              });
            }
            break;
          case "complete":
            ws.close();
            set({
              status: "completed",
              duration: event.duration_seconds ?? null,
              ws: null,
              heartbeat: "Complete",
              stats: event.stats
                ? {
                    llm_calls: event.stats.llm_calls || 0,
                    tool_calls: event.stats.tool_calls || 0,
                    tokens_in: event.stats.tokens_in || 0,
                    tokens_out: event.stats.tokens_out || 0,
                    total_tokens: event.stats.total_tokens || 0,
                    cost_usd: event.stats.cost_usd || 0,
                    cost_inr: event.stats.cost_inr || 0,
                    per_model: event.stats.per_model,
                  }
                : get().stats,
            });
            break;
          case "error":
            ws.close();
            set({ status: "error", error: event.message ?? "Unknown error", ws: null });
            break;
          case "stopped":
            ws.close();
            set({ status: "completed", ws: null, heartbeat: "Stopped by user" });
            break;
        }
      });

      set({ taskId, ws });
    } catch (e: any) {
      set({ status: "error", error: e.message });
    }
  },

  stop: async () => {
    const { taskId, ws } = get();
    if (!taskId) return;
    try {
      await stopAnalysis(taskId);
    } catch {}
    if (ws) {
      try { ws.close(); } catch {}
    }
    set({ status: "completed", ws: null, heartbeat: "Stopped by user" });
  },

      reset: () => {
        const ws = get().ws;
        if (ws) {
          try { ws.close(); } catch {}
        }
        set({
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
          stats: null,
          structuredPayloads: {},
        });
      },
    }),
    {
      name: "analysis-store",
      partialize: (state) => ({
        ticker: state.ticker,
        tradeDate: state.tradeDate,
        status: state.taskId ? state.status : "idle",  // don't persist "running" without a taskId
        reports: state.reports,
        debates: state.debates,
        riskDebates: state.riskDebates,
        signal: state.signal,
        duration: state.duration,
        stats: state.stats,
        structuredPayloads: state.structuredPayloads,
      }),
    }
  )
);
