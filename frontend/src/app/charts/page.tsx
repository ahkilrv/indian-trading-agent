"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { getChartData } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { HelpSection } from "@/components/HelpSection";
import { chartsHelp } from "@/lib/help-content";

const periods = ["1mo", "3mo", "6mo", "1y", "2y"];

export default function ChartsPage() {
  const [ticker, setTicker] = useState("RELIANCE");
  const [period, setPeriod] = useState("3mo");
  const [data, setData] = useState<any[]>([]);
  const [dataSource, setDataSource] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<any>(null);
  const disposed = useRef(false);

  const loadChart = useCallback(async (symbol?: string) => {
    const t = symbol || ticker;
    if (!t.trim()) return;
    setLoading(true);
    try {
      const result: any = await getChartData(t.trim(), period);
      setData(result.data || []);
      setDataSource(result.data_source || "");
    } catch {
      setData([]);
      setDataSource("");
    } finally {
      setLoading(false);
    }
  }, [ticker, period]);

  useEffect(() => {
    loadChart();
  }, [period]);

  useEffect(() => {
    if (!chartRef.current || data.length === 0) return;

    disposed.current = false;

    // Cleanup previous
    if (chartInstance.current) {
      try { chartInstance.current.remove(); } catch {}
      chartInstance.current = null;
    }

    // Dynamic import to avoid SSR issues
    let chart: any = null;

    (async () => {
      const lc = await import("lightweight-charts");

      if (disposed.current || !chartRef.current) return;

      chart = lc.createChart(chartRef.current, {
        layout: {
          background: { type: lc.ColorType.Solid, color: "transparent" },
          textColor: "#333",
        },
        grid: {
          vertLines: { color: "rgba(0,0,0,0.06)" },
          horzLines: { color: "rgba(0,0,0,0.06)" },
        },
        width: chartRef.current.clientWidth,
        height: 500,
        crosshair: { mode: 0 },
        timeScale: { borderColor: "rgba(0,0,0,0.1)" },
        rightPriceScale: { borderColor: "rgba(0,0,0,0.1)" },
      });

      if (disposed.current) {
        try { chart.remove(); } catch {}
        return;
      }

      const candleSeries = chart.addSeries(lc.CandlestickSeries, {
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderDownColor: "#ef4444",
        borderUpColor: "#22c55e",
        wickDownColor: "#ef4444",
        wickUpColor: "#22c55e",
      });

      candleSeries.setData(
        data.map((d: any) => ({
          time: d.time,
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close,
        }))
      );

      const volumeSeries = chart.addSeries(lc.HistogramSeries, {
        color: "#3b82f680",
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });

      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });

      volumeSeries.setData(
        data.map((d: any) => ({
          time: d.time,
          value: d.volume,
          color: d.close >= d.open ? "#22c55e40" : "#ef444440",
        }))
      );

      chart.timeScale().fitContent();
      chartInstance.current = chart;
    })();

    const handleResize = () => {
      if (chartInstance.current && chartRef.current) {
        try { chartInstance.current.applyOptions({ width: chartRef.current.clientWidth }); } catch {}
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      disposed.current = true;
      window.removeEventListener("resize", handleResize);
      if (chartInstance.current) {
        try { chartInstance.current.remove(); } catch {}
        chartInstance.current = null;
      }
      if (chart && chart !== chartInstance.current) {
        try { chart.remove(); } catch {}
      }
    };
  }, [data]);

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Charts</h1>
        <p className="text-sm text-muted-foreground">Interactive candlestick charts for NSE stocks</p>
      </div>

      <div className="flex gap-3 items-end">
        <div className="w-64">
          <Input
            placeholder="Enter ticker (e.g., RELIANCE)"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && loadChart()}
            className="font-sans"
          />
        </div>
        <Button onClick={() => loadChart()} disabled={loading}>
          {loading ? "Loading..." : "Load"}
        </Button>
        <div className="flex gap-1 ml-4">
          {periods.map((p) => (
            <Button
              key={p}
              variant={period === p ? "default" : "outline"}
              size="sm"
              onClick={() => setPeriod(p)}
            >
              {p}
            </Button>
          ))}
        </div>
        {dataSource && (
          <span className="text-xs text-muted-foreground ml-auto flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 inline-block" />
            Data: {dataSource}
          </span>
        )}
      </div>

      <Card>
        <CardContent className="p-4">
          <div
            ref={chartRef}
            className="w-full"
            style={{ minHeight: 500, display: data.length > 0 ? "block" : "none" }}
          />
          {data.length === 0 && (
            <div className="h-[500px] flex items-center justify-center text-muted-foreground">
              {loading ? "Loading chart data..." : "Enter a ticker and click Load to view chart"}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Help */}
      <HelpSection title="How to Read Charts" items={chartsHelp} />
    </div>
  );
}
