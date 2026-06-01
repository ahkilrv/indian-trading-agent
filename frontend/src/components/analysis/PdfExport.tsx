"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { FileDown, Loader2 } from "lucide-react";
import { exportPdf } from "@/lib/api";

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

interface PdfExportProps {
  ticker: string;
  tradeDate: string;
  signal: string | null;
  reports: Record<string, string>;
  debates: { bull: string; bear: string };
  riskDebates: { aggressive: string; conservative: string; neutral: string };
  stats: AnalysisStats | null;
  duration: number | null;
}

export function PdfExport({ ticker, tradeDate, signal, reports, debates, riskDebates, stats, duration }: PdfExportProps) {
  const [generating, setGenerating] = useState(false);

  const handleExport = async () => {
    setGenerating(true);
    try {
      const blob = await exportPdf({
        ticker,
        trade_date: tradeDate,
        signal,
        reports,
        debates,
        risk_debates: riskDebates,
        stats: stats as unknown as Record<string, unknown> | undefined,
        duration,
      });

      // Download the PDF
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${ticker}_analysis_${tradeDate}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("PDF export failed:", e);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleExport}
      disabled={generating}
    >
      {generating ? (
        <>
          <Loader2 className="h-3 w-3 animate-spin mr-2" />
          Generating PDF...
        </>
      ) : (
        <>
          <FileDown className="h-3 w-3 mr-2" />
          Export PDF
        </>
      )}
    </Button>
  );
}