"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { connectRecommendationsSSE, openPaperTrade } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { HelpSection } from "@/components/HelpSection";
import { Loader2, TrendingUp, TrendingDown, Sparkles, ChevronDown, ChevronUp, Target, Search, FlaskConical, Activity } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";
import { NextStep } from "@/components/NextStep";
import { TradingViewLink } from "@/components/TradingViewLink";

const recommendationsHelp = [
  {
    question: "What is this?",
    answer: "CONSOLIDATED RECOMMENDATION ENGINE. Runs ALL signals for EVERY stock using continuous scoring (no more binary thresholds):\n\n  \u2022 Gap Up/Down detection (continuous)\n  \u2022 Volume spike analysis (logarithmic)\n  \u2022 Breakout detection (proportional)\n  \u2022 Support/Resistance proximity (inverse-distance)\n  \u2022 RSI deviation position\n  \u2022 Momentum (5-day return)\n  \u2022 Trend (SMA alignment)\n  \u2022 Cyclical/seasonal patterns\n\nEvery stock gets a score and ALL are ranked. No more empty 'No signals' results.",
  },
  {
    question: "How does continuous scoring work?",
    answer: "Instead of binary thresholds (gap >= 2% yes/no), each factor contributes proportionally:\n\n  \u2022 Gap: gap_pct x 0.35 (capped at ±3)\n  \u2022 Volume: log2(ratio) x 0.75 (capped at ±3)\n  \u2022 Breakout: % above 20d high x 10 (capped at ±3)\n  \u2022 S/R: 1 / distance% (capped at ±3, stronger when closer)\n  \u2022 RSI: (50 - rsi) / 20 (capped at ±2)\n  \u2022 Trend: SMA deviation % x 3 (capped at ±3)\n  \u2022 Momentum: 5d return% x 0.3 (capped at ±2)\n  \u2022 Cyclical: avg month return% x 2 (capped at ±2)\n\nTotal possible score range: -21 to +21.\n\nRatings:\n  \u2022 Score >= 4: STRONG BUY\n  \u2022 Score >= 1.5: BUY\n  \u2022 Score -1.5 to 1.5: NEUTRAL (but still shown)\n  \u2022 Score <= -1.5: SELL\n  \u2022 Score <= -4: STRONG SELL",
  },
  {
    question: "How to use the recommendations?",
    answer: "Simple workflow:\n\n1. Click 'Get Recommendations' (results stream in as each stock is analyzed)\n2. Focus on high-scoring stocks first (highest absolute score)\n3. Click 'Signals' on interesting ones to see WHY it's recommended\n4. Click 'AI Analyze' to run AI analysis (Rs.15-25) on top 2-3 candidates\n5. Only take trades where AI agrees with the recommendation\n\nThe key benefit: you go from scanning 50-100 stocks manually to a ranked list in under 30 seconds.",
  },
  {
    question: "Why don't I see NEUTRAL stocks anymore?",
    answer: "You DO see them — all stocks are ranked by score. NEUTRAL just means the score is between -1.5 and +1.5 (no strong conviction). These stocks are still listed in the main 'Results' tab so you can see the full picture. The BUY/SELL tabs only show stocks with stronger conviction.",
  },
  {
    question: "What is the % estimated success?",
    answer: "A rough probability estimate based on:\n  \u2022 Baseline: 50% (random chance)\n  \u2022 +5% per point of absolute score (up to +30%)\n  \u2022 +2% per aligned signal (up to +15%)\n  \u2022 Max: 85% (never 100% certain)\n\nThis is an estimate based on signal strength, NOT guaranteed. Actual win rates depend on market conditions.",
  },
];

const ratingStyles: Record<string, { color: string; bg: string; border: string; icon: any }> = {
  "STRONG BUY": { color: "text-green-700", bg: "bg-green-100", border: "border-green-300", icon: TrendingUp },
  "BUY": { color: "text-green-600", bg: "bg-green-50", border: "border-green-200", icon: TrendingUp },
  "NEUTRAL": { color: "text-gray-500", bg: "bg-gray-50", border: "border-gray-200", icon: Activity },
  "SELL": { color: "text-red-600", bg: "bg-red-50", border: "border-red-200", icon: TrendingDown },
  "STRONG SELL": { color: "text-red-700", bg: "bg-red-100", border: "border-red-300", icon: TrendingDown },
};

const confidenceStyles: Record<string, string> = {
  HIGH: "bg-blue-100 text-blue-800 border-blue-300",
  MEDIUM: "bg-yellow-50 text-yellow-700 border-yellow-200",
  LOW: "bg-gray-50 text-gray-600 border-gray-200",
};

function RecommendationCard({ rec }: { rec: any }) {
  const [expanded, setExpanded] = useState(false);
  const style = ratingStyles[rec.direction] || ratingStyles.BUY;
  const Icon = style.icon;

  return (
    <Card className={`${style.border}`}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-3">
            <div className={`p-2 rounded-lg ${style.bg}`}>
              <Icon className={`h-5 w-5 ${style.color}`} />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-semibold text-lg">{rec.ticker} <TradingViewLink ticker={rec.ticker} className="ml-1" /></h3>
                <span className={`text-sm ${rec.change_pct >= 0 ? "text-green-600" : "text-red-600"}`}>
                  Rs.{rec.price} ({rec.change_pct >= 0 ? "+" : ""}{rec.change_pct}%)
                </span>
                <Badge className={`${style.bg} ${style.color} border`}>{rec.direction}</Badge>
                <Badge variant="outline" className={confidenceStyles[rec.confidence]}>
                  {rec.confidence} confidence
                </Badge>
                {rec.success_probability && (
                  <Badge variant="outline" className={rec.success_probability >= 70 ? "bg-green-100 text-green-800 border-green-300" : rec.success_probability >= 60 ? "bg-yellow-50 text-yellow-700 border-yellow-200" : "bg-gray-50 text-gray-600 border-gray-200"}>
                    {rec.success_probability}% estimated success
                  </Badge>
                )}
                <Badge variant="outline" className="text-xs">
                  Score: {rec.score >= 0 ? "+" : ""}{rec.score}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                {rec.bullish_signal_count > 0 && <span className="text-green-600">{rec.bullish_signal_count} bullish</span>}
                {rec.bullish_signal_count > 0 && rec.bearish_signal_count > 0 && <span> / </span>}
                {rec.bearish_signal_count > 0 && <span className="text-red-600">{rec.bearish_signal_count} bearish</span>}
                {rec.rsi !== null && <span> / RSI: {rec.rsi}</span>}
                {rec.signals && <span> / {rec.signals.length} signal{rec.signals.length !== 1 ? "s" : ""}</span>}
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => setExpanded(!expanded)}>
              {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              Signals
            </Button>
            <Button
              size="sm"
              variant="ghost"
              title="Open paper trade to track if this pick works"
              onClick={async () => {
                try {
                  await openPaperTrade({
                    ticker: rec.ticker,
                    source: "recommendation",
                    strategy: "Recommendation Engine (combined signals)",
                    signal: rec.direction,
                    score: rec.score,
                    confidence: rec.confidence,
                    success_probability: rec.success_probability,
                    triggered_signals: rec.signals,
                    stop_loss: rec.price ? Number((rec.price * (rec.direction?.includes("BUY") ? 0.97 : 1.03)).toFixed(2)) : undefined,
                    target_1: rec.price ? Number((rec.price * (rec.direction?.includes("BUY") ? 1.05 : 0.95)).toFixed(2)) : undefined,
                    time_horizon: "1_WEEK",
                  });
                  toast.success(`${rec.ticker} tracked at Rs.${rec.price}`, {
                    description: "Paper trade opened.",
                    duration: 6000,
                    action: {
                      label: "View Simulation",
                      onClick: () => { window.location.href = "/simulation"; },
                    },
                  });
                } catch (e: any) {
                  toast.error(e.message || "Failed to track");
                }
              }}
            >
              <FlaskConical className="h-3 w-3 mr-1" /> Track
            </Button>
            <Link href={`/analysis?ticker=${rec.ticker}`}>
              <Button size="sm" variant="outline" title="Run full AI analysis (costs ~Rs.15-25, takes 1-3 min)">
                <Target className="h-3 w-3 mr-1" /> AI Analyze
              </Button>
            </Link>
          </div>
        </div>

        {expanded && (
          <div className="mt-4 pt-4 border-t space-y-2">
            <p className="text-xs font-medium text-muted-foreground mb-2">WHY THIS RECOMMENDATION:</p>
            {rec.signals.map((s: any, i: number) => {
              const dirColor = s.direction === "BULLISH" ? "text-green-700 bg-green-50" : s.direction === "BEARISH" ? "text-red-700 bg-red-50" : "text-gray-600 bg-gray-50";
              return (
                <div key={i} className={`flex items-center justify-between p-2 rounded text-sm ${dirColor}`}>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs">{s.direction}</Badge>
                    <span>{s.type}</span>
                    <span className="text-muted-foreground">({s.value})</span>
                  </div>
                  <span className="text-xs font-mono">
                    {s.weight >= 0 ? "+" : ""}{s.weight} pts
                  </span>
                </div>
              );
            })}
            {rec.near_support != null && rec.near_resistance != null && (
              <div className="flex items-center justify-between pt-2 border-t">
                <span className="text-xs text-muted-foreground">60-day range:</span>
                <span className="text-xs">
                  Support: <span className="text-green-600">Rs.{rec.near_support}</span> • Resistance: <span className="text-red-600">Rs.{rec.near_resistance}</span>
                </span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}


function partitionByDirection(results: any[]) {
  return {
    strong_buys: results.filter((r) => r.direction === "STRONG BUY").sort((a, b) => b.score - a.score),
    buys: results.filter((r) => r.direction === "BUY").sort((a, b) => b.score - a.score),
    neutral: results.filter((r) => r.direction === "NEUTRAL").sort((a, b) => b.score - a.score),
    sells: results.filter((r) => r.direction === "SELL").sort((a, b) => a.score - b.score),
    strong_sells: results.filter((r) => r.direction === "STRONG SELL").sort((a, b) => a.score - b.score),
  };
}


export default function RecommendationsPage() {
  const [universe, setUniverse] = useState("nifty100");
  const [streaming, setStreaming] = useState(false);
  const [data, setData] = useState<any>(null);
  const [partialResults, setPartialResults] = useState<any[]>([]);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const esRef = useRef<EventSource | null>(null);

  const handleStop = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    setStreaming(false);
  }, []);

  useEffect(() => {
    return () => { esRef.current?.close(); };
  }, []);

  const handleRun = useCallback(() => {
    handleStop();
    setData(null);
    setPartialResults([]);
    setProgress({ done: 0, total: 0 });
    setStreaming(true);

    const es = connectRecommendationsSSE(universe, {
      onResult: (stock) => {
        setPartialResults((prev) => [...prev, stock]);
      },
      onProgress: (p) => {
        setProgress(p);
      },
      onComplete: (summary) => {
        setData(summary);
        setPartialResults([]);
        setStreaming(false);
        esRef.current = null;
      },
      onError: () => {
        setStreaming(false);
        esRef.current = null;
        if (!data) {
          toast.error("Stream connection lost. Try again.");
        }
      },
    });
    esRef.current = es;
  }, [universe, data, handleStop]);

  // Live-partition partial results for the progress tab display
  const partialBuckets = streaming && partialResults.length > 0
    ? partitionByDirection(partialResults)
    : null;

  // Final data buckets
  const allResults = streaming ? partialResults : (data?.results || []);
  const buckets = data ? {
    strong_buys: data.strong_buys || [],
    buys: data.buys || [],
    sells: data.sells || [],
    strong_sells: data.strong_sells || [],
    // Neutral computed from results not in any bucket
    neutral: (data.results || []).filter(
      (r: any) => !["STRONG BUY", "BUY", "SELL", "STRONG SELL"].includes(r.direction)
    ),
    total_analyzed: data.total_analyzed || 0,
    total_with_signals: data.total_with_signals || 0,
  } : null;

  const partialCounts = partialBuckets ? {
    strong_buys: partialBuckets.strong_buys.length,
    buys: partialBuckets.buys.length,
    sells: partialBuckets.sells.length,
    strong_sells: partialBuckets.strong_sells.length,
    neutral: partialBuckets.neutral.length,
    total_analyzed: progress.total,
    total_with_signals: partialResults.length,
  } : null;

  // Merge counts: prefer final data if available
  const counts = buckets || partialCounts;
  const totalRecs = counts
    ? counts.strong_buys + counts.buys + counts.sells + counts.strong_sells
    : 0;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Sparkles className="h-6 w-6 text-yellow-500" /> Recommendations
        </h1>
        <p className="text-sm text-muted-foreground">
          Unified recommendation engine with continuous scoring + progressive streaming. ALL stocks ranked — no more empty results.
        </p>
      </div>

      {/* Config */}
      <Card>
        <CardContent className="p-4">
          <div className="flex gap-3 items-end flex-wrap">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Universe</label>
              <div className="flex gap-1">
                {[
                  { value: "nifty50", label: "NIFTY 50" },
                  { value: "nifty100", label: "NIFTY 100" },
                  { value: "bse250", label: "BSE 250" },
                ].map((u) => (
                  <Button
                    key={u.value}
                    variant={universe === u.value ? "default" : "outline"}
                    size="sm"
                    onClick={() => setUniverse(u.value)}
                    disabled={streaming}
                  >
                    {u.label}
                  </Button>
                ))}
              </div>
            </div>
            <Button onClick={handleRun} disabled={streaming}>
              {streaming ? (
                <><Loader2 className="h-4 w-4 animate-spin mr-2" />Analyzing...</>
              ) : (
                <><Sparkles className="h-4 w-4 mr-2" />Get Recommendations</>
              )}
            </Button>
            {streaming && (
              <Button variant="outline" size="sm" onClick={handleStop}>
                Stop
              </Button>
            )}
          </div>
          {streaming && (
            <p className="text-xs text-muted-foreground mt-3 flex items-center gap-2">
              <Loader2 className="h-3 w-3 animate-spin" />
              Analyzing {progress.done}/{progress.total} {universe.toUpperCase()} stocks — results stream in as each completes...
            </p>
          )}
        </CardContent>
      </Card>

      {/* Summary */}
      {counts && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <Card className="border-green-300">
            <CardContent className="p-3 text-center">
              <p className="text-xs text-muted-foreground">Strong Buy</p>
              <p className="text-2xl font-bold text-green-700">{counts.strong_buys}</p>
            </CardContent>
          </Card>
          <Card className="border-green-200">
            <CardContent className="p-3 text-center">
              <p className="text-xs text-muted-foreground">Buy</p>
              <p className="text-2xl font-bold text-green-600">{counts.buys}</p>
            </CardContent>
          </Card>
          <Card className="border-gray-200">
            <CardContent className="p-3 text-center">
              <p className="text-xs text-muted-foreground">Neutral</p>
              <p className="text-2xl font-bold text-gray-500">{counts.neutral}</p>
            </CardContent>
          </Card>
          <Card className="border-red-200">
            <CardContent className="p-3 text-center">
              <p className="text-xs text-muted-foreground">Sell</p>
              <p className="text-2xl font-bold text-red-600">{counts.sells}</p>
            </CardContent>
          </Card>
          <Card className="border-red-300">
            <CardContent className="p-3 text-center">
              <p className="text-xs text-muted-foreground">Strong Sell</p>
              <p className="text-2xl font-bold text-red-700">{counts.strong_sells}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-3 text-center">
              <p className="text-xs text-muted-foreground">Analyzed</p>
              <p className="text-2xl font-bold">{counts.total_analyzed}</p>
              <p className="text-xs text-muted-foreground">{counts.total_with_signals} with data</p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Live streaming results — show as they arrive */}
      {streaming && partialResults.length > 0 && !data && (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground mb-1">
            Live results — {partialResults.length} stocks analyzed so far, sorted by score:
          </p>
          {partialResults
            .sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
            .slice(0, 10)
            .map((rec: any) => (
              <RecommendationCard key={`live-${rec.ticker}-${partialResults.indexOf(rec)}`} rec={rec} />
            ))}
          {partialResults.length > 10 && (
            <p className="text-xs text-muted-foreground text-center">
              ... and {partialResults.length - 10} more (waiting for completion)
            </p>
          )}
        </div>
      )}

      {/* Final results — Tabs */}
      {data && totalRecs > 0 && (
        <Tabs defaultValue="strong_buys">
          <TabsList>
            <TabsTrigger value="strong_buys">Strong Buy ({buckets?.strong_buys.length})</TabsTrigger>
            <TabsTrigger value="buys">Buy ({buckets?.buys.length})</TabsTrigger>
            <TabsTrigger value="neutral">Neutral ({buckets?.neutral.length})</TabsTrigger>
            <TabsTrigger value="sells">Sell ({buckets?.sells.length})</TabsTrigger>
            <TabsTrigger value="strong_sells">Strong Sell ({buckets?.strong_sells.length})</TabsTrigger>
          </TabsList>

          {(["strong_buys", "buys", "neutral", "sells", "strong_sells"] as const).map((key) => (
            <TabsContent key={key} value={key} className="space-y-3">
              {(buckets?.[key]?.length ?? 0) === 0 ? (
                <Card>
                  <CardContent className="p-8 text-center text-muted-foreground">
                    No {key.replace("_", " ")} recommendations.
                  </CardContent>
                </Card>
              ) : (
                (buckets?.[key] ?? []).map((rec: any) => <RecommendationCard key={rec.ticker} rec={rec} />)
              )}
            </TabsContent>
          ))}
        </Tabs>
      )}

      {/* All stocks ranking (even neutral ones) */}
      {data && buckets && (
        <details className="mt-6">
          <summary className="text-sm font-medium cursor-pointer text-muted-foreground hover:text-foreground">
            Show full ranking ({allResults.length} stocks)
          </summary>
          <div className="mt-3 space-y-1 max-h-96 overflow-y-auto">
            {allResults
              .sort((a: any, b: any) => Math.abs(b.score) - Math.abs(a.score))
              .map((rec: any, i: number) => (
                <div
                  key={rec.ticker}
                  className="flex items-center justify-between px-3 py-1.5 text-sm rounded hover:bg-muted/50"
                >
                  <span className="text-xs text-muted-foreground w-6">{i + 1}.</span>
                  <span className="font-medium w-28">{rec.ticker}</span>
                  <span className="text-muted-foreground w-20">Rs.{rec.price}</span>
                  <span className={`w-16 font-mono ${rec.score >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {rec.score >= 0 ? "+" : ""}{rec.score}
                  </span>
                  <Badge variant="outline" className={`text-xs ${rec.direction === "STRONG BUY" ? "bg-green-100 text-green-800 border-green-300" : rec.direction === "BUY" ? "bg-green-50 text-green-700 border-green-200" : rec.direction === "SELL" ? "bg-red-50 text-red-700 border-red-200" : rec.direction === "STRONG SELL" ? "bg-red-100 text-red-800 border-red-300" : "bg-gray-50 text-gray-500 border-gray-200"}`}>
                    {rec.direction}
                  </Badge>
                  <span className="text-xs text-muted-foreground flex-1 text-right">
                    {rec.signals?.length || 0} signals · RSI {rec.rsi ?? "—"}
                  </span>
                </div>
              ))}
          </div>
        </details>
      )}

      {data && totalRecs === 0 && counts && counts.total_analyzed > 0 && (
        <Card>
          <CardContent className="p-8 text-center">
            <p className="text-muted-foreground">All stocks scored NEUTRAL — market is quiet today.</p>
            <p className="text-xs text-muted-foreground mt-2">
              Check the full ranking below for stocks closest to a signal.
            </p>
          </CardContent>
        </Card>
      )}

      {!data && !streaming && (
        <Card className="h-[200px] flex items-center justify-center">
          <CardContent className="text-center">
            <p className="text-muted-foreground">Click &quot;Get Recommendations&quot; to scan all {universe.toUpperCase()} stocks and get ranked trade ideas.</p>
            <p className="text-xs text-muted-foreground mt-2">
              Results stream in progressively — you&apos;ll see stocks appear as each is analyzed.
            </p>
          </CardContent>
        </Card>
      )}

      {data && totalRecs > 0 && (
        <NextStep
          title="Deep-analyze your top pick with AI"
          description="Click 'AI Analyze' on a Strong Buy for entry/SL/target from the 10-agent AI pipeline (~Rs.15-25)"
          href="/analysis"
          buttonText="Open Analysis"
          icon={Search}
        />
      )}

      <HelpSection title="How to Use Recommendations" items={recommendationsHelp} />
    </div>
  );
}
