"use client";

import { useEffect, useState } from "react";
import { getFiiDiiBias, getFiiDiiToday } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
  Loader2,
  Building2,
  AlertCircle,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

const biasColors: Record<string, { bg: string; border: string; text: string; icon: any }> = {
  BULLISH: { bg: "bg-green-50", border: "border-green-200", text: "text-green-800", icon: TrendingUp },
  BEARISH: { bg: "bg-red-50", border: "border-red-200", text: "text-red-800", icon: TrendingDown },
  MIXED: { bg: "bg-yellow-50", border: "border-yellow-200", text: "text-yellow-800", icon: Minus },
  NEUTRAL: { bg: "bg-gray-50", border: "border-gray-200", text: "text-gray-700", icon: Minus },
};

function formatCr(value: number | null | undefined): string {
  if (value == null) return "—";
  const abs = Math.abs(value);
  const sign = value >= 0 ? "+" : "-";
  return `${sign}Rs.${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr`;
}

export function FIIDIIBanner() {
  const [bias, setBias] = useState<any>(null);
  const [today, setToday] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const load = async (force: boolean = false) => {
    setLoading(true);
    try {
      const [dataRes, biasRes] = await Promise.all([
        getFiiDiiToday(force).catch(() => null),
        getFiiDiiBias().catch(() => null),
      ]);
      setToday(dataRes);
      setBias(biasRes);
    } catch {
      setToday(null);
      setBias(null);
    }
    setLoading(false);
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await load(true);
    setRefreshing(false);
  };

  useEffect(() => {
    load();
  }, []);

  if (loading) {
    return (
      <Card>
        <CardContent className="p-4 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading FII/DII flow...
        </CardContent>
      </Card>
    );
  }

  // Derive today's values: prefer today endpoint, fall back to bias
  const fiiToday: number | null = today?.fii_net ?? bias?.today_fii_net ?? null;
  const diiToday: number | null = today?.dii_net ?? bias?.today_dii_net ?? null;
  const dataDate: string | null = today?.date ?? bias?.data_date ?? null;
  const source: string | null = today?.source ?? null;

  // Show error only if BOTH endpoints returned nothing
  if (!today?.ok && fiiToday == null && diiToday == null) {
    return (
      <Card className="border-yellow-200 bg-yellow-50/30">
        <CardContent className="p-4 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <AlertCircle className="h-4 w-4 text-yellow-700" />
            <span className="text-yellow-800">
              FII/DII data unavailable. Moneycontrol may not have published today's data yet (typically available by ~5:30 PM).
            </span>
          </div>
          <Button size="sm" variant="outline" onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <RefreshCw className="h-3 w-3 mr-1" />}
            Try Again
          </Button>
        </CardContent>
      </Card>
    );
  }

  // When today's data exists but bias computation couldn't (first load / no history),
  // create a minimal bias to avoid crashing on null fields
  const resolvedBias = bias ?? {};
  const style = biasColors[resolvedBias.bias] || (fiiToday != null && fiiToday < 0 ? biasColors.BEARISH : biasColors.NEUTRAL);
  const Icon = style.icon;
  const confidence = resolvedBias.confidence ?? "—";
  const reasoning = resolvedBias.reasoning ?? null;
  const fii5d: number | null = resolvedBias.fii_5d_net ?? null;
  const dii5d: number | null = resolvedBias.dii_5d_net ?? null;
  const scoreAdj: number | null = resolvedBias.score_adjustment ?? null;

  return (
    <Card className={`${style.border} ${style.bg}`}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-white">
              <Building2 className={`h-5 w-5 ${style.text}`} />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">
                Institutional Flow ({dataDate ?? "N/A"})
                {source && <span className="ml-1 opacity-60">via {source}</span>}
              </p>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold text-sm">FII: <span className={fiiToday != null && fiiToday >= 0 ? "text-green-700" : "text-red-700"}>{formatCr(fiiToday)}</span></span>
                <span className="font-semibold text-sm">DII: <span className={diiToday != null && diiToday >= 0 ? "text-green-700" : "text-red-700"}>{formatCr(diiToday)}</span></span>
                {resolvedBias.bias && (
                  <Badge variant="outline" className={`${style.text} border-current`}>
                    <Icon className="h-3 w-3 mr-1" />
                    {resolvedBias.bias} ({confidence})
                  </Badge>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {reasoning && (
              <Button size="sm" variant="ghost" onClick={() => setExpanded(!expanded)}>
                {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                Why
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={handleRefresh} disabled={refreshing} title="Refresh data">
              {refreshing ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            </Button>
          </div>
        </div>

        {expanded && reasoning && (
          <div className="mt-3 pt-3 border-t border-current/10 space-y-2 text-sm">
            <p className={style.text}>{reasoning}</p>
            <div className="grid grid-cols-2 gap-3 mt-2">
              <div className="p-2 rounded bg-white/60">
                <p className="text-xs text-muted-foreground">Today's FII Net</p>
                <p className={`font-semibold ${fiiToday != null && fiiToday >= 0 ? "text-green-700" : "text-red-700"}`}>
                  {formatCr(fiiToday)}
                </p>
                <p className="text-xs text-muted-foreground">5-day: {formatCr(fii5d)}</p>
              </div>
              <div className="p-2 rounded bg-white/60">
                <p className="text-xs text-muted-foreground">Today's DII Net</p>
                <p className={`font-semibold ${diiToday != null && diiToday >= 0 ? "text-green-700" : "text-red-700"}`}>
                  {formatCr(diiToday)}
                </p>
                <p className="text-xs text-muted-foreground">5-day: {formatCr(dii5d)}</p>
              </div>
            </div>
            {scoreAdj != null && (
              <p className="text-xs text-muted-foreground italic">
                The Recommendation Engine adjusts all stock scores by{" "}
                <span className="font-mono">{scoreAdj >= 0 ? "+" : ""}{scoreAdj}</span> points based on this bias.
                {resolvedBias.bias === "BEARISH" && " Be selective on long positions today."}
                {resolvedBias.bias === "BULLISH" && " Tailwind for long positions today."}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
