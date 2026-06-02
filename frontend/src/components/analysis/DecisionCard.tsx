"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { TrendingUp, TrendingDown, Minus, AlertTriangle, Target, Shield, Flag, Clock, Percent, FlaskConical, Loader2 } from "lucide-react";
import { TradingViewLink } from "@/components/TradingViewLink";
import { openPaperTrade } from "@/lib/api";
import { toast } from "sonner";

const signalConfig: Record<string, { color: string; bg: string; icon: any; label: string }> = {
  BUY: { color: "text-green-400", bg: "bg-green-500/10 border-green-500/30", icon: TrendingUp, label: "BUY" },
  STRONG_BUY: { color: "text-green-400", bg: "bg-green-500/10 border-green-500/30", icon: TrendingUp, label: "STRONG BUY" },
  OVERWEIGHT: { color: "text-green-300", bg: "bg-green-500/10 border-green-500/20", icon: TrendingUp, label: "OVERWEIGHT" },
  HOLD: { color: "text-yellow-400", bg: "bg-yellow-500/10 border-yellow-500/30", icon: Minus, label: "HOLD" },
  SELL: { color: "text-red-400", bg: "bg-red-500/10 border-red-500/30", icon: TrendingDown, label: "SELL" },
  SHORT: { color: "text-red-400", bg: "bg-red-500/10 border-red-500/30", icon: AlertTriangle, label: "SHORT" },
  UNDERWEIGHT: { color: "text-red-300", bg: "bg-red-500/10 border-red-500/20", icon: TrendingDown, label: "UNDERWEIGHT" },
};

interface Props {
  signal: string | null;
  ticker: string;
  duration?: number | null;
  portfolioPayload?: Record<string, any> | null;
  taskId?: string | null;
}

function ScoreBar({ value, max, color, label }: { value: number; max: number; color: string; label: string }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono font-medium">{((value || 0) * 100).toFixed(0)}%</span>
      </div>
      <div className="h-1.5 bg-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function DecisionCard({ signal, ticker, duration, portfolioPayload, taskId }: Props) {
  const [tracking, setTracking] = useState(false);
  if (!signal) return null;

  const config = signalConfig[signal] || signalConfig.HOLD;
  const Icon = config.icon;
  const pm = portfolioPayload;

  const isTradeable = signal === "BUY" || signal === "STRONG BUY" || signal === "SELL" || signal === "SHORT";
  const hasStrategyParams = pm?.stop_loss != null && pm?.target_1 != null;

  const handleTrack = async () => {
    if (!pm) return;
    setTracking(true);
    try {
      // Map portfolio manager rating to signal/direction
      const rating = pm.rating || signal;
      const direction = rating.includes("BUY") ? "LONG" : rating.includes("SELL") || rating === "SHORT" ? "SHORT" : "LONG";

      const result: any = await openPaperTrade({
        ticker,
        source: "ai_analysis",
        strategy: "AI Multi-Agent Pipeline",
        signal: rating,
        confidence: pm.confidence_score ? (pm.confidence_score >= 0.7 ? "HIGH" : pm.confidence_score >= 0.4 ? "MEDIUM" : "LOW") : undefined,
        success_probability: pm.confidence_score ? Math.round(pm.confidence_score * 100) : undefined,
        score: pm.confidence_score || undefined,
        stop_loss: pm.stop_loss,
        target_1: pm.target_1,
        target_2: pm.target_2,
        time_horizon: pm.time_horizon,
        analysis_task_id: taskId || undefined,
      });

      if (result.ok) {
        toast.success(
          <div>
            <strong>{ticker}</strong> paper trade opened at ₹{result.entry_price}
            <br />
            <span className="text-xs text-muted-foreground">
              SL: ₹{pm.stop_loss} · T1: ₹{pm.target_1}{pm.target_2 ? ` · T2: ₹${pm.target_2}` : ""}
            </span>
          </div>
        );
      } else {
        toast.error(result.error || "Failed to open paper trade");
      }
    } catch (e: any) {
      toast.error(e.message || "Failed to open paper trade");
    } finally {
      setTracking(false);
    }
  };

  return (
    <Card className={`${config.bg} border-2`}>
      <CardContent className="p-5 space-y-4">
        {/* Header: Signal + Ticker */}
        <div className="flex items-center gap-3">
          <div className={`p-2.5 rounded-full ${config.bg}`}>
            <Icon className={`h-7 w-7 ${config.color}`} />
          </div>
          <div className="flex-1">
            <p className="text-sm text-muted-foreground">Final Decision</p>
            <p className={`text-2xl font-bold ${config.color}`}>
              {ticker} — {signal}
              <TradingViewLink ticker={ticker} className="ml-2 align-middle" />
            </p>
            {(pm?.time_horizon || pm?.risk_reward_ratio) && (
              <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
                {pm?.time_horizon && (
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {pm.time_horizon.replace(/_/g, " ")}
                  </span>
                )}
                {pm?.risk_reward_ratio && (
                  <span className="flex items-center gap-1">
                    <Percent className="h-3 w-3" />
                    R:R {pm.risk_reward_ratio.toFixed(2)}
                  </span>
                )}
              </div>
            )}
          </div>
          <div className="flex flex-col items-end gap-2 shrink-0">
            {duration && (
              <div className="text-right">
                <p className="text-xs text-muted-foreground">Duration</p>
                <p className="text-lg font-sans">{Math.round(duration)}s</p>
              </div>
            )}
            {isTradeable && hasStrategyParams && (
              <Button
                size="sm"
                variant="outline"
                className="text-xs"
                onClick={handleTrack}
                disabled={tracking}
              >
                {tracking ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <FlaskConical className="h-3 w-3 mr-1" />}
                {tracking ? "Opening..." : "Track with AI Levels"}
              </Button>
            )}
          </div>
        </div>

        {/* Price Levels — only show if portfolio manager data exists */}
        {(pm?.entry_price || pm?.stop_loss || pm?.target_1) && (
          <div className="grid grid-cols-4 gap-2">
            {pm?.entry_price != null && (
              <div className="p-2 rounded bg-background/50 text-center">
                <div className="flex items-center justify-center gap-1 text-xs text-muted-foreground mb-0.5">
                  <Target className="h-3 w-3" /> Entry
                </div>
                <div className="font-mono font-bold text-sm">
                  ₹{typeof pm.entry_price === "number" ? pm.entry_price.toFixed(2) : pm.entry_price}
                </div>
              </div>
            )}
            {pm?.stop_loss != null && (
              <div className="p-2 rounded bg-red-500/5 text-center">
                <div className="flex items-center justify-center gap-1 text-xs text-red-400 mb-0.5">
                  <Shield className="h-3 w-3" /> Stop Loss
                </div>
                <div className="font-mono font-bold text-sm text-red-400">
                  ₹{typeof pm.stop_loss === "number" ? pm.stop_loss.toFixed(2) : pm.stop_loss}
                </div>
              </div>
            )}
            {pm?.target_1 != null && (
              <div className="p-2 rounded bg-green-500/5 text-center">
                <div className="flex items-center justify-center gap-1 text-xs text-green-400 mb-0.5">
                  <Flag className="h-3 w-3" /> Target 1
                </div>
                <div className="font-mono font-bold text-sm text-green-400">
                  ₹{typeof pm.target_1 === "number" ? pm.target_1.toFixed(2) : pm.target_1}
                </div>
              </div>
            )}
            {pm?.target_2 != null && (
              <div className="p-2 rounded bg-emerald-500/5 text-center">
                <div className="flex items-center justify-center gap-1 text-xs text-emerald-400 mb-0.5">
                  <Flag className="h-3 w-3" /> Target 2
                </div>
                <div className="font-mono font-bold text-sm text-emerald-400">
                  ₹{typeof pm.target_2 === "number" ? pm.target_2.toFixed(2) : pm.target_2}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Position Size + Confidence bars */}
        {(pm?.position_size_pct != null || pm?.confidence_score != null) && (
          <div className="space-y-2">
            {pm?.position_size_pct != null && (
              <ScoreBar value={pm.position_size_pct} max={1.0} color="bg-blue-500" label="Position Size" />
            )}
            {pm?.confidence_score != null && (
              <ScoreBar value={pm.confidence_score} max={1.0} color="bg-purple-500" label="Confidence" />
            )}
          </div>
        )}

        {/* Executive Summary */}
        {pm?.executive_summary && (
          <div className="text-sm leading-relaxed p-3 bg-background/50 rounded">{pm.executive_summary}</div>
        )}

        {/* Investment Thesis (collapsible with one-line preview) */}
        {pm?.investment_thesis && (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer hover:text-foreground font-medium">Full Investment Thesis</summary>
            <p className="mt-2 leading-relaxed">{pm.investment_thesis}</p>
          </details>
        )}

        {/* Rejection Reason (if HOLD/SELL) */}
        {pm?.rejection_reason && (
          <div className="text-xs p-2 bg-red-500/10 text-red-400 rounded">{pm.rejection_reason}</div>
        )}
      </CardContent>
    </Card>
  );
}
