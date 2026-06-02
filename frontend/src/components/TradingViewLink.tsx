"use client";

import { ExternalLink } from "lucide-react";

interface Props {
  ticker: string;
  className?: string;
}

/** Opens TradingView chart for an NSE stock in a new tab.
 *  Strips .NS/.BO suffix and builds URL: NSE:{bare_ticker}
 */
export function TradingViewLink({ ticker, className = "" }: Props) {
  const bare = (ticker || "").toUpperCase().replace(/\.NS$/, "").replace(/\.BO$/, "");
  const url = `https://www.tradingview.com/chart/?symbol=NSE:${bare}`;

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className={`inline-flex items-center shrink-0 text-muted-foreground hover:text-blue-500 transition-colors ${className}`}
      title={`View ${bare} on TradingView`}
      onClick={(e) => e.stopPropagation()}
    >
      <ExternalLink className="h-3.5 w-3.5" />
    </a>
  );
}
