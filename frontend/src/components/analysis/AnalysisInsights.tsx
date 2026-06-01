"use client";

import { Card, CardContent } from "@/components/ui/card";
import { ReactNode } from "react";

// ── Types ─────────────────────────────────────────────────────────
type Payload = Record<string, any> | null | undefined;

interface Props {
  payloads: Record<string, Payload>; // agent → structured payload dict
}

// ── Helpers ───────────────────────────────────────────────────────
const ScoreBar = ({ value, max, color = "blue", label }: { value: number; max: number; color?: string; label?: string }) => {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const colorMap: Record<string, string> = {
    blue: "bg-blue-500",
    green: "bg-green-500",
    red: "bg-red-500",
    amber: "bg-amber-500",
    purple: "bg-purple-500",
    teal: "bg-teal-500",
  };
  return (
    <div className="space-y-1">
      {label && <span className="text-xs text-muted-foreground">{label}</span>}
      <div className="flex items-center gap-2">
        <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
          <div className={`h-full rounded-full transition-all ${colorMap[color] || "bg-blue-500"}`} style={{ width: `${pct}%` }} />
        </div>
        <span className="text-xs font-mono tabular-nums w-14 text-right">{typeof value === "number" ? value.toFixed(1) : value}</span>
      </div>
    </div>
  );
};

const VerdictBadge = ({ verdict }: { verdict: string | undefined }) => {
  const colorMap: Record<string, string> = {
    BULLISH: "bg-green-100 text-green-800 border-green-300",
    BEARISH: "bg-red-100 text-red-800 border-red-300",
    NEUTRAL: "bg-slate-100 text-slate-600 border-slate-300",
    BUY: "bg-green-100 text-green-800 border-green-300",
    STRONG_BUY: "bg-emerald-100 text-emerald-800 border-emerald-400",
    HOLD: "bg-amber-100 text-amber-800 border-amber-300",
    SELL: "bg-red-100 text-red-800 border-red-300",
    SHORT: "bg-red-200 text-red-900 border-red-400",
  };
  if (!verdict) return null;
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold border ${colorMap[verdict] || "bg-muted text-muted-foreground border-border"}`}>
      {verdict}
    </span>
  );
};

const PriceRow = ({ label, value }: { label: string; value: number | string | undefined }) => {
  if (value === undefined || value === null) return null;
  const display = typeof value === "number" ? `₹${value.toFixed(2)}` : `${value}`;
  return (
    <div className="flex justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono font-medium">{display}</span>
    </div>
  );
};

interface InsightCardProps {
  title: string;
  icon: string;
  badge?: ReactNode;
  children: ReactNode;
}
const InsightCard = ({ title, icon, badge, children }: InsightCardProps) => (
  <Card className="border-border/50">
    <CardContent className="p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm">{icon}</span>
          <h3 className="text-sm font-semibold">{title}</h3>
        </div>
        {badge}
      </div>
      {children}
    </CardContent>
  </Card>
);

// ── Agent-Specific Explanations ───────────────────────────────────

function MarketInsight({ data }: { data: Record<string, any> }) {
  const trend = data.current_trend?.replace(/_/g, " ");
  const support = (data.key_support || []) as number[];
  const resistance = (data.key_resistance || []) as number[];
  return (
    <InsightCard title="Market Analyst" icon="📊" badge={<VerdictBadge verdict={data.technical_verdict} />}>
      <div className="text-xs space-y-2">
        <div className="flex items-center gap-2 text-muted-foreground">
          <span>Trend: <strong className="text-foreground">{trend}</strong></span>
          <span>·</span>
          <span>Momentum: <strong className="text-foreground">{data.momentum_state}</strong></span>
        </div>
        <div className="grid grid-cols-2 gap-1">
          <div className="space-y-0.5">
            <span className="text-muted-foreground">Support Levels</span>
            {support.map((s: number, i: number) => <div key={i} className="font-mono text-green-700">S{i + 1}: ₹{s}</div>)}
          </div>
          <div className="space-y-0.5">
            <span className="text-muted-foreground">Resistance Levels</span>
            {resistance.map((r: number, i: number) => <div key={i} className="font-mono text-red-700">R{i + 1}: ₹{r}</div>)}
          </div>
        </div>
        <div className="text-muted-foreground">
          Institutional flow: <strong className="text-foreground">{data.institutional_flow_bias?.replace(/_/g, " ")}</strong>
        </div>
        <div className="text-xs p-2 bg-muted/50 rounded">
          <strong>What this means:</strong>{" "}
          {data.technical_verdict === "BULLISH"
            ? `The stock is in a ${trend?.toLowerCase()}, trading above key support of ₹${support[0]}. Technical indicators favor upward movement.`
            : data.technical_verdict === "BEARISH"
            ? `The stock is showing ${trend?.toLowerCase()}, approaching support at ₹${support[0]}. Downward pressure expected.`
            : `The stock is range-bound between ₹${support[0]} and ₹${resistance[0]}. No clear directional bias from technicals.`}
        </div>
      </div>
    </InsightCard>
  );
}

function NewsInsight({ data }: { data: Record<string, any> }) {
  return (
    <InsightCard title="News Analyst" icon="📰" badge={<VerdictBadge verdict={data.news_verdict} />}>
      <div className="text-xs space-y-2">
        <ScoreBar value={data.sentiment_score} max={1.0}
          color={data.sentiment_score > 0 ? "green" : data.sentiment_score < 0 ? "red" : "blue"}
          label={`Sentiment Score: ${((data.sentiment_score || 0) > 0 ? "+" : "") + (data.sentiment_score || 0).toFixed(2)}`}
        />
        {data.catalyst_identified && (
          <div className="text-amber-700 font-medium">Catalyst detected: {data.primary_driver}</div>
        )}
        <div className="text-muted-foreground text-xs p-2 bg-muted/50 rounded">
          <strong>Source verification:</strong> {data.driver_source?.substring(0, 150) || "No direct quote available"}
        </div>
        <div className="text-xs p-2 bg-muted/50 rounded">
          <strong>What this means:</strong>{" "}
          {data.news_verdict === "BULLISH"
            ? "Recent news carries a positive tone. A fundamental catalyst suggests upward price potential."
            : data.news_verdict === "BEARISH"
            ? "Recent news is predominantly negative. Watch for the identified risk factor to play out."
            : "News sentiment is mixed — no strong directional signal from headlines alone."}
        </div>
      </div>
    </InsightCard>
  );
}

function SocialInsight({ data }: { data: Record<string, any> }) {
  return (
    <InsightCard title="Social Media Analyst" icon="💬" badge={<VerdictBadge verdict={data.social_verdict} />}>
      <div className="text-xs space-y-2">
        <ScoreBar value={data.aggregate_sentiment} max={1.0}
          color={data.aggregate_sentiment > 0 ? "green" : data.aggregate_sentiment < 0 ? "red" : "blue"}
          label={`Aggregate Sentiment: ${data.aggregate_sentiment > 0 ? "+" : ""}${data.aggregate_sentiment}`}
        />
        <div className="flex gap-3 text-muted-foreground">
          <span>
            Retail Engagement:{" "}
            <strong className={data.is_high_engagement ? "text-orange-600" : "text-foreground"}>
              {data.is_high_engagement ? "HIGH (2x spike)" : "Normal"}
            </strong>
          </span>
          <span>
            Divergence: <strong className={data.sentiment_divergence ? "text-red-600" : "text-foreground"}>
              {data.sentiment_divergence ? "Detected" : "None"}
            </strong>
          </span>
        </div>
        {data.sentiment_divergence && (
          <div className="text-red-700 text-xs p-2 bg-red-50 rounded">
            Crowd sentiment contradicts price trend: {data.divergence_rationale}
          </div>
        )}
      </div>
    </InsightCard>
  );
}

function FundamentalsInsight({ data }: { data: Record<string, any> }) {
  return (
    <InsightCard title="Fundamentals Analyst" icon="📈" badge={<VerdictBadge verdict={data.overall_fundamental_verdict} />}>
      <div className="text-xs space-y-2">
        <ScoreBar value={data.valuation_score} max={10} color="teal" label={`Valuation Score: ${data.valuation_score} / 10 (lower = undervalued)`} />
        <div className="flex items-center gap-2 text-muted-foreground">
          <span>Financial Health: <strong className="text-foreground">{data.health_status}</strong></span>
        </div>
        <div className="space-y-1 text-xs">
          <div className="text-green-700">Strength: {data.primary_strength}</div>
          <div className="text-red-700">Weakness: {data.primary_weakness}</div>
        </div>
      </div>
    </InsightCard>
  );
}

function ResearcherInsight({ data, role }: { data: Record<string, any>; role: "bull" | "bear" }) {
  const isBull = role === "bull";
  return (
    <InsightCard
      title={isBull ? "Bull Researcher" : "Bear Researcher"}
      icon={isBull ? "🐂" : "🐻"}
      badge={<VerdictBadge verdict={isBull ? "BULLISH" : "BEARISH"} />}
    >
      <div className="text-xs space-y-2">
        <div className="font-medium">{data.thesis_summary}</div>
        <div className="text-muted-foreground">
          Catalyst: <strong className="text-foreground">{data.primary_catalyst}</strong>
        </div>
        <ScoreBar value={data.confidence_score} max={1.0} color={isBull ? "green" : "red"}
          label={`Confidence: ${((data.confidence_score || 0) * 100).toFixed(0)}%`}
        />
        <div className="font-mono text-sm font-semibold">Target: ₹{data.target_price}</div>
        {data.supporting_metrics?.length > 0 && (
          <div className="text-xs text-muted-foreground">
            Evidence:{" "}
            {data.supporting_metrics.map((m: any, i: number) => (
              <span key={i} className="after:content-['_·_'] last:after:content-none">
                <strong>{m.metric_name}</strong>: {m.value} (source: {m.source})
              </span>
            ))}
          </div>
        )}
        <div className="text-xs text-orange-600 italic">Ignored risk: {data.fatal_flaw_ignored}</div>
      </div>
    </InsightCard>
  );
}

function ResearchManagerInsight({ data }: { data: Record<string, any> }) {
  return (
    <InsightCard title="Research Manager" icon="⚖️" badge={<VerdictBadge verdict={data.recommendation} />}>
      <div className="text-xs space-y-2">
        <div className="font-medium text-sm">{data.rationale}</div>
        <div className="space-y-1">
          <PriceRow label="Entry Zone" value={data.entry_zone} />
          <PriceRow label="Stop Loss" value={data.stop_loss} />
          <PriceRow label="Target 1" value={data.target_1} />
          <PriceRow label="Target 2" value={data.target_2} />
        </div>
        <div className="flex items-center gap-2 text-muted-foreground">
          <span>Horizon: <strong className="text-foreground">{data.time_horizon?.replace(/_/g, " ")}</strong></span>
        </div>
        <div className="text-red-600 text-xs">Key risk: {data.key_risk}</div>
      </div>
    </InsightCard>
  );
}

function TraderInsight({ data }: { data: Record<string, any> }) {
  return (
    <InsightCard title="Trader" icon="📋" badge={<VerdictBadge verdict={data.action} />}>
      <div className="text-xs space-y-2">
        <div className="flex items-center gap-3">
          <div className="font-mono text-xs">Type: <strong>{data.order_type}</strong></div>
          <div className="font-mono text-xs">R:R = <strong>{data.risk_reward_ratio?.toFixed(2)}</strong></div>
        </div>
        <div className="space-y-1">
          <PriceRow label="Entry" value={data.entry_price} />
          <PriceRow label="Stop Loss" value={data.stop_loss} />
          <PriceRow label="Target 1" value={data.target_1} />
          <PriceRow label="Target 2" value={data.target_2} />
        </div>
        <ScoreBar value={data.position_size_pct} max={1.0} color="purple"
          label={`Position Size: ${((data.position_size_pct || 0) * 100).toFixed(0)}% of capital`}
        />
        <div className="text-xs text-muted-foreground">{data.execution_notes}</div>
      </div>
    </InsightCard>
  );
}

function RiskDebaterInsight({ data, role }: { data: Record<string, any>; role: string }) {
  const icons: Record<string, string> = { aggressive: "🔥", conservative: "🛡️", neutral: "🧮" };
  const labels: Record<string, string> = { aggressive: "Aggressive Risk Officer", conservative: "Conservative Risk Officer", neutral: "Neutral Risk Officer" };

  return (
    <InsightCard title={labels[role] || role} icon={icons[role] || "📐"} badge={<VerdictBadge verdict={data.verdict} />}>
      <div className="text-xs space-y-2">
        <div className="flex gap-3">
          <ScoreBar value={data.bull_target_probability} max={1.0} color="green"
            label={`Bull prob: ${((data.bull_target_probability || 0) * 100).toFixed(0)}%`}
          />
          <ScoreBar value={data.bear_target_probability} max={1.0} color="red"
            label={`Bear prob: ${((data.bear_target_probability || 0) * 100).toFixed(0)}%`}
          />
        </div>
        <div className="text-xs font-mono">Risk/Reward: {data.risk_reward_ratio?.toFixed(2)}</div>
        <ScoreBar value={data.position_size_recommendation_pct} max={1.0} color="amber"
          label={`Recommended size: ${((data.position_size_recommendation_pct || 0) * 100).toFixed(0)}%`}
        />
        <div className="text-xs text-muted-foreground">{data.key_rationale}</div>
        <div className="text-xs text-red-600">Critical risk: {data.critical_risk_flagged}</div>
        {data.structural_risk && (
          <div className="text-xs p-2 bg-red-100 text-red-800 rounded font-medium">
            VETO triggered — {data.rejection_reason}
          </div>
        )}
      </div>
    </InsightCard>
  );
}

function PortfolioManagerInsight({ data }: { data: Record<string, any> }) {
  return (
    <InsightCard title="Portfolio Manager" icon="🎯" badge={<VerdictBadge verdict={data.rating} />}>
      <div className="text-xs space-y-2">
        <div className="text-sm font-semibold">{data.executive_summary}</div>
        <ScoreBar value={data.confidence_score} max={1.0} color="blue"
          label={`Confidence: ${((data.confidence_score || 0) * 100).toFixed(0)}%`}
        />
        <div className="space-y-1">
          <PriceRow label="Entry" value={data.entry_price} />
          <PriceRow label="Stop Loss" value={data.stop_loss} />
          <PriceRow label="Target 1" value={data.target_1} />
          <PriceRow label="Target 2" value={data.target_2} />
        </div>
        <div className="text-xs text-muted-foreground">
          Size: {((data.position_size_pct || 0) * 100).toFixed(0)}% · R:R {data.risk_reward_ratio?.toFixed(2)} · {data.time_horizon?.replace(/_/g, " ")}
        </div>
        {data.rejection_reason && (
          <div className="text-xs p-2 bg-red-50 text-red-700 rounded">{data.rejection_reason}</div>
        )}
        <div className="text-xs p-2 bg-muted/50 rounded">
          <strong>Thesis:</strong> {data.investment_thesis}
        </div>
      </div>
    </InsightCard>
  );
}

// ── Data Source Badge ──────────────────────────────────────────────

const sourceMap: Record<string, { source: string; desc: string }> = {
  market: { source: "NSE India + pandas-ta", desc: "Technical analysis from NSE sidecar with 130+ indicators" },
  news: { source: "SerpAPI Google News + RSS", desc: "Structured news from SerpAPI, RSS feeds from Google News & Economic Times" },
  social: { source: "SerpAPI YouTube + Forums + Trends", desc: "YouTube video views, Reddit/forum discussions, Google search trends" },
  fundamentals: { source: "yfinance", desc: "Income statement, balance sheet, cash flow from Yahoo Finance" },
  bull: { source: "Upstream analyst reports", desc: "Synthesizes Market + News + Social + Fundamentals findings" },
  bear: { source: "Upstream analyst reports", desc: "Synthesizes Market + News + Social + Fundamentals findings" },
  research_manager: { source: "Bull vs Bear debate", desc: "Adjudicates conflicting arguments and sets price targets" },
  trader: { source: "Research Manager verdict", desc: "Converts verdict into executable trade plan with risk parameters" },
  risk_aggressive: { source: "Bull + Bear payloads", desc: "Risk-weighted assessment with aggressive position sizing" },
  risk_conservative: { source: "Bull + Bear payloads", desc: "Conservative assessment with structural risk detection and veto power" },
  risk_neutral: { source: "Bull + Bear payloads", desc: "Mathematical risk-reward calculation from target prices" },
  portfolio_manager: { source: "All 3 risk debaters", desc: "Final trade decision synthesized from Aggressive, Conservative, and Neutral assessments" },
};

function DataSourceBadge({ agent }: { agent: string }) {
  const info = sourceMap[agent];
  if (!info) return null;
  return (
    <div className="text-[10px] text-muted-foreground bg-muted/30 px-1.5 py-0.5 rounded">
      <span className="font-medium">Source:</span> {info.source}
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────

const withScoreBar = (Component: any) => Component;

function renderAgent(agent: string, payload: Record<string, any> | null | undefined) {
  if (!payload || Object.keys(payload).length === 0) return null;

  const badge = <DataSourceBadge agent={agent} />;

  switch (agent) {
    case "market": return <div key={agent}>{badge}<MarketInsight data={payload} /></div>;
    case "news": return <div key={agent}>{badge}<NewsInsight data={payload} /></div>;
    case "social": return <div key={agent}>{badge}<SocialInsight data={payload} /></div>;
    case "fundamentals": return <div key={agent}>{badge}<FundamentalsInsight data={payload} /></div>;
    case "bull": return <div key={agent}>{badge}<ResearcherInsight data={payload} role="bull" /></div>;
    case "bear": return <div key={agent}>{badge}<ResearcherInsight data={payload} role="bear" /></div>;
    case "research_manager": return <div key={agent}>{badge}<ResearchManagerInsight data={payload} /></div>;
    case "trader": return <div key={agent}>{badge}<TraderInsight data={payload} /></div>;
    case "risk_aggressive": return <div key={agent}>{badge}<RiskDebaterInsight data={payload} role="aggressive" /></div>;
    case "risk_conservative": return <div key={agent}>{badge}<RiskDebaterInsight data={payload} role="conservative" /></div>;
    case "risk_neutral": return <div key={agent}>{badge}<RiskDebaterInsight data={payload} role="neutral" /></div>;
    case "portfolio_manager": return <div key={agent}>{badge}<PortfolioManagerInsight data={payload} /></div>;
    default: return null;
  }
}

// Agent display order
const agentOrder = ["market", "news", "social", "fundamentals", "bull", "bear", "research_manager", "trader", "risk_aggressive", "risk_conservative", "risk_neutral", "portfolio_manager"];

export function AnalysisInsights({ payloads }: Props) {
  const hasPayloads = Object.values(payloads).some((p) => p != null && Object.keys(p).length > 0);
  if (!hasPayloads) return null;

  const renderedCards = agentOrder
    .map((agent) => renderAgent(agent, payloads[agent]))
    .filter(Boolean);

  if (renderedCards.length === 0) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">Analysis Insights</h2>
        <span className="text-xs text-muted-foreground">
          Structured agent findings &mdash; each score verified against Pydantic schemas
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {renderedCards}
      </div>
    </div>
  );
}
