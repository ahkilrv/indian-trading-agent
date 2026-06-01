export interface Quote {
  ticker: string;
  name: string;
  price: number;
  change: number;
  change_percent: number;
  volume: number;
  high: number;
  low: number;
  open: number;
  prev_close: number;
  market_cap?: number;
  pe_ratio?: number;
  fifty_two_week_high?: number;
  fifty_two_week_low?: number;
  data_source?: string;
}

export interface ChartDataPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ChartData {
  ticker: string;
  period: string;
  interval: string;
  data: ChartDataPoint[];
  data_source?: string;
}

export interface MarketStatus {
  session: string;
  is_trading_day: boolean;
  nifty: { price: number; change: number; change_percent: number };
  banknifty: { price: number; change: number; change_percent: number };
  data_source?: string;
}

export interface WatchlistItem {
  ticker: string;
  symbol: string;
  exchange: string;
  name: string;
  price: number | null;
  change: number | null;
  change_percent: number | null;
  added_at: string;
}

export interface AnalysisRequest {
  ticker: string;
  trade_date: string;
  analysts: string[];
  max_debate_rounds: number;
  max_risk_discuss_rounds: number;
}

export interface AnalysisResult {
  task_id: string;
  ticker: string;
  trade_date: string;
  signal: string;
  market_report?: string;
  sentiment_report?: string;
  news_report?: string;
  fundamentals_report?: string;
  investment_plan?: string;
  trader_investment_plan?: string;
  final_trade_decision?: string;
  bull_history?: string;
  bear_history?: string;
  risk_aggressive_history?: string;
  risk_conservative_history?: string;
  risk_neutral_history?: string;
  stats?: Record<string, number>;
  duration_seconds?: number;
  created_at?: string;
  // Structured Pydantic payloads (deserialized from DB JSON columns)
  market_analysis?: Record<string, any>;
  fundamentals_analysis?: Record<string, any>;
  news_analysis?: Record<string, any>;
  social_sentiment?: Record<string, any>;
  bull_researcher_payload?: Record<string, any>;
  bear_researcher_payload?: Record<string, any>;
  research_manager_verdict?: Record<string, any>;
  trader_execution_plan?: Record<string, any>;
  aggressive_debater_payload?: Record<string, any>;
  conservative_debater_payload?: Record<string, any>;
  neutral_debater_payload?: Record<string, any>;
  portfolio_manager_payload?: Record<string, any>;
}

export interface AnalysisHistoryItem {
  task_id: string;
  ticker: string;
  trade_date: string;
  signal: string;
  duration_seconds: number;
  entry_price?: number;
  exit_price?: number;
  pnl_pct?: number;
  pnl_status?: string;
  created_at: string;
}

export interface BacktestTrade {
  trade_date: string;
  ticker: string;
  signal: string;
  entry_price: number;
  exit_price: number;
  pnl_pct: number;
  pnl_amount: number;
  cumulative_pnl: number;
  portfolio_value: number;
  duration_seconds: number;
}

export interface BacktestResult {
  backtest_id: string;
  ticker: string;
  initial_capital: number;
  final_portfolio_value: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  total_pnl: number;
  status: string;
  trades: BacktestTrade[];
}

export interface BacktestWSEvent {
  type: "trade" | "status" | "complete" | "error";
  message?: string;
  total_dates?: number;
  // trade fields
  trade_date?: string;
  signal?: string;
  entry_price?: number;
  exit_price?: number;
  pnl_pct?: number;
  pnl_amount?: number;
  cumulative_pnl?: number;
  portfolio_value?: number;
  // complete fields
  total_trades?: number;
  winning_trades?: number;
  losing_trades?: number;
  win_rate?: number;
  total_return_pct?: number;
  max_drawdown_pct?: number;
  total_pnl?: number;
}

export interface WSEvent {
  type: "report" | "debate" | "risk_debate" | "signal" | "agent_status" | "complete" | "error" | "stats" | "structured_payload";
  section?: string;
  content?: string;
  side?: string;
  agent?: string;
  status?: string;
  decision?: string;
  ticker?: string;
  message?: string;
  duration_seconds?: number;
  llm_calls?: number;
  tool_calls?: number;
  tokens_in?: number;
  tokens_out?: number;
  // Structured payload fields
  field?: string;
  data?: Record<string, any>;
}

export type Signal = "STRONG BUY" | "BUY" | "HOLD" | "SELL" | "SHORT" | "OVERWEIGHT" | "UNDERWEIGHT";
