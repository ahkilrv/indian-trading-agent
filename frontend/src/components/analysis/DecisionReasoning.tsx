"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowRight, Lightbulb } from "lucide-react";
import { useState } from "react";

interface Props {
  payloads: Record<string, any>;
  signal: string | null;
}

function AgentReasoning({ agent, icon, verdict, children }: { agent: string; icon: React.ReactNode; verdict?: string | null; children: React.ReactNode }) {
  const v = verdict ?? "";
  const vColor = v === "BULLISH" || v === "BUY" || v === "STRONG_BUY" ? "text-green-600" :
    v === "BEARISH" || v === "SELL" || v === "SHORT" ? "text-red-600" : "text-amber-600";

  return (
    <div className="border-l-2 border-border pl-3 py-1 space-y-1">
      <div className="flex items-center gap-2">
        <span className="shrink-0">{icon}</span>
        <span className="text-sm font-semibold">{agent}</span>
        {v && <span className={`text-xs font-mono ${vColor}`}>({v})</span>}
      </div>
      <div className="text-xs text-muted-foreground leading-relaxed">{children}</div>
    </div>
  );
}

function Arrow() {
  return <div className="flex justify-center text-muted-foreground/40"><ArrowRight className="h-4 w-4 rotate-90" /></div>;
}

export function DecisionReasoning({ payloads, signal }: Props) {
  const [open, setOpen] = useState(false);

  const hasData = payloads.market || payloads.news || payloads.social || payloads.fundamentals;
  if (!hasData) return null;

  const m = payloads.market || {};
  const n = payloads.news || {};
  const s = payloads.social || {};
  const f = payloads.fundamentals || {};
  const bull = payloads.bull || {};
  const bear = payloads.bear || {};
  const rm = payloads.research_manager || {};
  const pm = payloads.portfolio_manager || {};
  const agg = payloads.risk_aggressive || {};
  const cons = payloads.risk_conservative || {};
  const neut = payloads.risk_neutral || {};

  const support = (m.key_support || []) as number[];
  const resistance = (m.key_resistance || []) as number[];

  return (
    <Card className="border-border/50">
      <CardHeader className="pb-2 cursor-pointer" onClick={() => setOpen(!open)}>
        <CardTitle className="text-sm flex items-center gap-2">
          <Lightbulb className="h-4 w-4 text-amber-400" />
          How the AI reached this decision
          <span className="text-xs text-muted-foreground font-normal ml-auto">
            {open ? "▲ collapse" : "▼ expand"}
          </span>
        </CardTitle>
      </CardHeader>
      {open && (
        <CardContent className="pt-0 space-y-3">
          {/* ── Step 1: Market ── */}
          <AgentReasoning agent="1. Market Analyst" icon="📊" verdict={m.technical_verdict}>
            <p>
              Trend: <strong>{String(m.current_trend || "N/A").replace(/_/g, " ")}</strong>.{" "}
              Momentum: <strong>{m.momentum_state || "N/A"}</strong>.
              {m.technical_verdict === "BULLISH" ? " Technicals favor upward movement." :
                m.technical_verdict === "BEARISH" ? " Technicals indicate downward pressure." :
                " Technicals are mixed."}
            </p>
            {support.length > 0 && (
              <p className="text-[11px]">
                Support: {support.slice(0, 3).map((v: number, i: number) => (
                  <span key={i} className="font-mono text-green-700">₹{v}{i < support.slice(0, 3).length - 1 ? ", " : ""}</span>
                ))}
                {" · "}
                Resistance: {resistance.slice(0, 3).map((v: number, i: number) => (
                  <span key={i} className="font-mono text-red-700">₹{v}{i < resistance.slice(0, 3).length - 1 ? ", " : ""}</span>
                ))}
              </p>
            )}
            {m.institutional_flow_bias && (
              <p className="text-[11px]">Institutional flow: {String(m.institutional_flow_bias).replace(/_/g, " ")}</p>
            )}
          </AgentReasoning>

          <Arrow />

          {/* ── Step 2: Sentiment (Social + News) ── */}
          <AgentReasoning agent="2. Sentiment Analysis" icon="💬" verdict={s.social_verdict || n.news_verdict}>
            {s.social_verdict && (
              <p>
                Social sentiment: <strong>{s.aggregate_sentiment}</strong> ({s.social_verdict}).{" "}
                {s.is_high_engagement ? "High retail engagement detected. " : ""}
                {s.sentiment_divergence ? `⚠️ ${s.divergence_rationale}` : ""}
              </p>
            )}
            {n.sentiment_score != null && (
              <p>
                News sentiment: <strong>{Number(n.sentiment_score) > 0 ? "+" : ""}{n.sentiment_score}</strong> ({n.news_verdict}).{" "}
                {n.catalyst_identified ? `Key driver: ${n.primary_driver}` : "No major catalyst detected."}
              </p>
            )}
          </AgentReasoning>

          <Arrow />

          {/* ── Step 3: Fundamentals ── */}
          <AgentReasoning agent="3. Fundamentals" icon="📈" verdict={f.overall_fundamental_verdict}>
            <p>
              Valuation score: <strong>{f.valuation_score}/10</strong> (lower = undervalued).{" "}
              Health: <strong>{f.health_status}</strong>.
              {f.primary_strength && <> Strength: {f.primary_strength}.</>}
              {f.primary_weakness && <> Risk: {f.primary_weakness}.</>}
            </p>
          </AgentReasoning>

          <Arrow />

          {/* ── Step 4: Bull vs Bear ── */}
          <AgentReasoning agent="4. Bull vs Bear Debate" icon="⚖️" verdict={rm.recommendation}>
            <div className="grid grid-cols-2 gap-2 mt-1">
              <div className="p-1.5 bg-green-500/5 rounded">
                <p className="text-xs font-semibold text-green-600">🐂 Bull Case</p>
                <p className="text-[10px]">{bull.thesis_summary || "—"}</p>
                <p className="text-[10px] font-mono mt-0.5">Target: ₹{bull.target_price || "—"} (confidence {(bull.confidence_score || 0) * 100}%)</p>
                {bull.supporting_metrics?.length > 0 && (
                  <p className="text-[10px] text-muted-foreground">
                    Evidence: {bull.supporting_metrics.map((m: any, i: number) => (
                      <span key={i}>{m.metric_name}: {m.value}{i < bull.supporting_metrics.length - 1 ? ", " : ""}</span>
                    ))}
                  </p>
                )}
                <p className="text-[10px] text-orange-500 italic">Ignored: {bull.fatal_flaw_ignored || "—"}</p>
              </div>
              <div className="p-1.5 bg-red-500/5 rounded">
                <p className="text-xs font-semibold text-red-600">🐻 Bear Case</p>
                <p className="text-[10px]">{bear.thesis_summary || "—"}</p>
                <p className="text-[10px] font-mono mt-0.5">Target: ₹{bear.target_price || "—"} (confidence {(bear.confidence_score || 0) * 100}%)</p>
                {bear.supporting_metrics?.length > 0 && (
                  <p className="text-[10px] text-muted-foreground">
                    Evidence: {bear.supporting_metrics.map((m: any, i: number) => (
                      <span key={i}>{m.metric_name}: {m.value}{i < bear.supporting_metrics.length - 1 ? ", " : ""}</span>
                    ))}
                  </p>
                )}
                <p className="text-[10px] text-orange-500 italic">Ignored: {bear.fatal_flaw_ignored || "—"}</p>
              </div>
            </div>
          </AgentReasoning>

          {/* ── Step 5: Research Manager Verdict ── */}
          {rm.recommendation && (
            <>
              <Arrow />
              <AgentReasoning agent="5. Research Manager" icon="🎯" verdict={rm.recommendation}>
                <p><strong>{rm.rationale}</strong></p>
                <p className="text-[11px]">
                  Entry zone: {rm.entry_zone || "—"} · Time horizon: {rm.time_horizon?.replace(/_/g, " ") || "—"} · Key risk: {rm.key_risk || "—"}
                </p>
                {rm.bull_arguments_accepted?.length > 0 && (
                  <p className="text-[11px] text-green-700">
                    Bull arguments accepted: {rm.bull_arguments_accepted.join("; ")}
                  </p>
                )}
                {rm.bear_arguments_accepted?.length > 0 && (
                  <p className="text-[11px] text-red-700">
                    Bear arguments acknowledged: {rm.bear_arguments_accepted.join("; ")}
                  </p>
                )}
              </AgentReasoning>
            </>
          )}

          {/* ── Step 6: Risk Assessment ── */}
          {(agg.verdict || cons.verdict || neut.verdict) && (
            <>
              <Arrow />
              <AgentReasoning agent="6. Risk Assessment" icon="🛡️">
                <div className="grid grid-cols-3 gap-1.5 mt-1 text-[10px]">
                  <div className="p-1 rounded bg-muted/30 text-center">
                    <span className="font-semibold">Aggressive</span>
                    <div className="font-mono">{agg.verdict || "—"}</div>
                    <div className="text-muted-foreground">size {((agg.position_size_recommendation_pct || 0) * 100).toFixed(0)}%</div>
                  </div>
                  <div className="p-1 rounded bg-muted/30 text-center">
                    <span className="font-semibold">Conservative</span>
                    <div className="font-mono">{cons.verdict || "—"}</div>
                    <div className="text-muted-foreground">size {((cons.position_size_recommendation_pct || 0) * 100).toFixed(0)}%</div>
                    {cons.structural_risk && <div className="text-red-500">VETO: {cons.rejection_reason?.substring(0, 40)}</div>}
                  </div>
                  <div className="p-1 rounded bg-muted/30 text-center">
                    <span className="font-semibold">Neutral</span>
                    <div className="font-mono">{neut.verdict || "—"}</div>
                    <div className="text-muted-foreground">R:R {neut.risk_reward_ratio?.toFixed(2) || "—"}</div>
                  </div>
                </div>
              </AgentReasoning>
            </>
          )}

          {/* ── Step 7: Final Decision ── */}
          <Arrow />
          <AgentReasoning agent="7. Portfolio Manager — Final Decision" icon="🎯" verdict={signal}>
            {pm.executive_summary && <p>{pm.executive_summary}</p>}
            {pm.investment_thesis && <p className="text-[11px] mt-1 opacity-70">{pm.investment_thesis}</p>}
          </AgentReasoning>
        </CardContent>
      )}
    </Card>
  );
}
