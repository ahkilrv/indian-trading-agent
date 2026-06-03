"""SQLite/PostgreSQL database for watchlist, analysis, backtests, and settings.

All SQL targets PostgreSQL syntax. Auto-translates to SQLite for local dev.
"""

import json
import os
from datetime import datetime
from contextlib import contextmanager

from backend.db_adapter import get_db


def ensure_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker TEXT PRIMARY KEY,
                exchange TEXT DEFAULT 'NSE',
                name TEXT,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_history (
                task_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                signal TEXT,
                market_report TEXT,
                sentiment_report TEXT,
                news_report TEXT,
                fundamentals_report TEXT,
                investment_plan TEXT,
                trader_investment_plan TEXT,
                final_trade_decision TEXT,
                bull_history TEXT,
                bear_history TEXT,
                risk_aggressive_history TEXT,
                risk_conservative_history TEXT,
                risk_neutral_history TEXT,
                stats TEXT,
                duration_seconds REAL,
                entry_price REAL,
                exit_price REAL,
                pnl_amount REAL,
                pnl_pct REAL,
                pnl_status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_runs (
                backtest_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                initial_capital REAL DEFAULT 100000,
                position_size_pct REAL DEFAULT 10,
                enable_learning BOOLEAN DEFAULT FALSE,
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                losing_trades INTEGER DEFAULT 0,
                total_return_pct REAL DEFAULT 0,
                max_drawdown_pct REAL DEFAULT 0,
                final_portfolio_value REAL,
                status TEXT DEFAULT 'running',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_trades (
                id SERIAL PRIMARY KEY,
                backtest_id TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                signal TEXT,
                entry_price REAL,
                exit_price REAL,
                pnl_amount REAL,
                pnl_pct REAL,
                cumulative_pnl REAL,
                portfolio_value REAL,
                duration_seconds REAL,
                FOREIGN KEY (backtest_id) REFERENCES backtest_runs(backtest_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id SERIAL PRIMARY KEY,
                ticker TEXT NOT NULL,
                source TEXT,
                strategy TEXT,
                direction TEXT,
                signal TEXT,
                score REAL,
                confidence TEXT,
                success_probability INTEGER,
                triggered_signals TEXT,
                entry_price REAL NOT NULL,
                entry_date TEXT DEFAULT CURRENT_DATE,
                entry_datetime TEXT DEFAULT CURRENT_TIMESTAMP,
                price_1d REAL,
                price_3d REAL,
                price_5d REAL,
                price_10d REAL,
                pnl_1d_pct REAL,
                pnl_3d_pct REAL,
                pnl_5d_pct REAL,
                pnl_10d_pct REAL,
                status TEXT DEFAULT 'active',
                notes TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS verdict_history (
                snapshot_date TEXT PRIMARY KEY,
                verdict TEXT NOT NULL,
                label TEXT,
                action TEXT,
                caution_count INTEGER,
                favorable_count INTEGER,
                caution_flags TEXT,
                favorable_flags TEXT,
                position_size_pct REAL,
                max_trades_today INTEGER,
                min_conviction TEXT,
                nifty_close REAL,
                nifty_close_1d REAL,
                nifty_close_3d REAL,
                nifty_close_5d REAL,
                nifty_return_1d_pct REAL,
                nifty_return_3d_pct REAL,
                nifty_return_5d_pct REAL,
                outcome_1d TEXT,
                outcome_3d TEXT,
                outcome_5d TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shadow_trades (
                ticker TEXT NOT NULL,
                signal_date TEXT NOT NULL,
                signal TEXT,
                score REAL,
                confidence TEXT,
                success_probability INTEGER,
                triggered_signals TEXT,
                regime_at_entry TEXT,
                entry_price REAL NOT NULL,
                price_1d REAL,
                price_3d REAL,
                price_5d REAL,
                price_10d REAL,
                pnl_1d_pct REAL,
                pnl_3d_pct REAL,
                pnl_5d_pct REAL,
                pnl_10d_pct REAL,
                user_tracked INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker, signal_date)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recommender_backtests (
                id SERIAL PRIMARY KEY,
                run_id TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                signal TEXT,
                score REAL,
                confidence TEXT,
                success_probability INTEGER,
                entry_price REAL,
                return_1d REAL,
                return_3d REAL,
                return_5d REAL,
                return_10d REAL,
                outcome_1d TEXT,
                outcome_5d TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def _migrate_analysis_history_columns(conn):
    for col in (
        ("market_analysis", "TEXT"),
        ("fundamentals_analysis", "TEXT"),
        ("news_analysis", "TEXT"),
        ("social_sentiment", "TEXT"),
        ("bull_researcher_payload", "TEXT"),
        ("bear_researcher_payload", "TEXT"),
        ("research_manager_verdict", "TEXT"),
        ("trader_execution_plan", "TEXT"),
        ("aggressive_debater_payload", "TEXT"),
        ("conservative_debater_payload", "TEXT"),
        ("neutral_debater_payload", "TEXT"),
        ("portfolio_manager_payload", "TEXT"),
    ):
        try:
            conn.execute(f"ALTER TABLE analysis_history ADD COLUMN {col[0]} {col[1]}")
        except Exception:
            pass


# --- Watchlist ---

def get_watchlist() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM watchlist ORDER BY added_at DESC").fetchall()
        return rows


def add_to_watchlist(ticker: str, exchange: str = "NSE", name: str = None):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO watchlist (ticker, exchange, name) VALUES (%s, %s, %s) "
            "ON CONFLICT (ticker) DO UPDATE SET exchange = EXCLUDED.exchange, name = EXCLUDED.name",
            (ticker.upper(), exchange, name),
        )


def remove_from_watchlist(ticker: str):
    with get_db() as conn:
        conn.execute("DELETE FROM watchlist WHERE ticker = %s", (ticker.upper(),))


# --- Analysis History ---

def save_analysis(task_id: str, data: dict):
    with get_db() as conn:
        _migrate_analysis_history_columns(conn)
        conn.execute(
            """INSERT INTO analysis_history
            (task_id, ticker, trade_date, signal, market_report, sentiment_report,
             news_report, fundamentals_report, investment_plan, trader_investment_plan,
             final_trade_decision, bull_history, bear_history,
             risk_aggressive_history, risk_conservative_history, risk_neutral_history,
             stats, duration_seconds,
             market_analysis, fundamentals_analysis, news_analysis, social_sentiment,
             bull_researcher_payload, bear_researcher_payload,
             research_manager_verdict, trader_execution_plan,
             aggressive_debater_payload, conservative_debater_payload,
             neutral_debater_payload, portfolio_manager_payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (task_id) DO UPDATE SET
            ticker = EXCLUDED.ticker, trade_date = EXCLUDED.trade_date,
            signal = EXCLUDED.signal, market_report = EXCLUDED.market_report,
            sentiment_report = EXCLUDED.sentiment_report,
            news_report = EXCLUDED.news_report,
            fundamentals_report = EXCLUDED.fundamentals_report,
            investment_plan = EXCLUDED.investment_plan,
            trader_investment_plan = EXCLUDED.trader_investment_plan,
            final_trade_decision = EXCLUDED.final_trade_decision,
            bull_history = EXCLUDED.bull_history,
            bear_history = EXCLUDED.bear_history,
            risk_aggressive_history = EXCLUDED.risk_aggressive_history,
            risk_conservative_history = EXCLUDED.risk_conservative_history,
            risk_neutral_history = EXCLUDED.risk_neutral_history,
            stats = EXCLUDED.stats,
            duration_seconds = EXCLUDED.duration_seconds,
            market_analysis = EXCLUDED.market_analysis,
            fundamentals_analysis = EXCLUDED.fundamentals_analysis,
            news_analysis = EXCLUDED.news_analysis,
            social_sentiment = EXCLUDED.social_sentiment,
            bull_researcher_payload = EXCLUDED.bull_researcher_payload,
            bear_researcher_payload = EXCLUDED.bear_researcher_payload,
            research_manager_verdict = EXCLUDED.research_manager_verdict,
            trader_execution_plan = EXCLUDED.trader_execution_plan,
            aggressive_debater_payload = EXCLUDED.aggressive_debater_payload,
            conservative_debater_payload = EXCLUDED.conservative_debater_payload,
            neutral_debater_payload = EXCLUDED.neutral_debater_payload,
            portfolio_manager_payload = EXCLUDED.portfolio_manager_payload""",
            (
                task_id,
                data.get("ticker"),
                data.get("trade_date"),
                data.get("signal"),
                data.get("market_report"),
                data.get("sentiment_report"),
                data.get("news_report"),
                data.get("fundamentals_report"),
                data.get("investment_plan"),
                data.get("trader_investment_plan"),
                data.get("final_trade_decision"),
                data.get("bull_history"),
                data.get("bear_history"),
                data.get("risk_aggressive_history"),
                data.get("risk_conservative_history"),
                data.get("risk_neutral_history"),
                json.dumps(data.get("stats")) if data.get("stats") else None,
                data.get("duration_seconds"),
                json.dumps(data.get("market_analysis")) if data.get("market_analysis") else None,
                json.dumps(data.get("fundamentals_analysis")) if data.get("fundamentals_analysis") else None,
                json.dumps(data.get("news_analysis")) if data.get("news_analysis") else None,
                json.dumps(data.get("social_sentiment")) if data.get("social_sentiment") else None,
                json.dumps(data.get("bull_researcher_payload")) if data.get("bull_researcher_payload") else None,
                json.dumps(data.get("bear_researcher_payload")) if data.get("bear_researcher_payload") else None,
                json.dumps(data.get("research_manager_verdict")) if data.get("research_manager_verdict") else None,
                json.dumps(data.get("trader_execution_plan")) if data.get("trader_execution_plan") else None,
                json.dumps(data.get("aggressive_debater_payload")) if data.get("aggressive_debater_payload") else None,
                json.dumps(data.get("conservative_debater_payload")) if data.get("conservative_debater_payload") else None,
                json.dumps(data.get("neutral_debater_payload")) if data.get("neutral_debater_payload") else None,
                json.dumps(data.get("portfolio_manager_payload")) if data.get("portfolio_manager_payload") else None,
            ),
        )


def update_analysis_pnl(task_id: str, entry_price: float, exit_price: float, pnl_amount: float, pnl_pct: float, pnl_status: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE analysis_history SET entry_price=%s, exit_price=%s, pnl_amount=%s, pnl_pct=%s, pnl_status=%s WHERE task_id=%s",
            (entry_price, exit_price, pnl_amount, pnl_pct, pnl_status, task_id),
        )


def get_analysis(task_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM analysis_history WHERE task_id = %s", (task_id,)).fetchone()
        if row:
            for col in (
                "stats", "market_analysis", "fundamentals_analysis",
                "news_analysis", "social_sentiment",
                "bull_researcher_payload", "bear_researcher_payload",
                "research_manager_verdict", "trader_execution_plan",
                "aggressive_debater_payload", "conservative_debater_payload",
                "neutral_debater_payload", "portfolio_manager_payload",
            ):
                if row.get(col):
                    try:
                        row[col] = json.loads(row[col])
                    except (json.JSONDecodeError, TypeError):
                        pass
            return row
        return None


def get_analysis_history(limit: int = 50, offset: int = 0) -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            """SELECT task_id, ticker, trade_date, signal, duration_seconds,
                      entry_price, exit_price, pnl_pct, pnl_status, created_at
               FROM analysis_history ORDER BY created_at DESC LIMIT %s OFFSET %s""",
            (limit, offset),
        ).fetchall()


# --- Backtest ---

def save_backtest_run(backtest_id: str, data: dict):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO backtest_runs
            (backtest_id, ticker, initial_capital, position_size_pct, enable_learning,
             total_trades, winning_trades, losing_trades, total_return_pct,
             max_drawdown_pct, final_portfolio_value, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (backtest_id) DO UPDATE SET
            ticker = EXCLUDED.ticker, initial_capital = EXCLUDED.initial_capital,
            position_size_pct = EXCLUDED.position_size_pct,
            enable_learning = EXCLUDED.enable_learning,
            total_trades = EXCLUDED.total_trades,
            winning_trades = EXCLUDED.winning_trades,
            losing_trades = EXCLUDED.losing_trades,
            total_return_pct = EXCLUDED.total_return_pct,
            max_drawdown_pct = EXCLUDED.max_drawdown_pct,
            final_portfolio_value = EXCLUDED.final_portfolio_value,
            status = EXCLUDED.status""",
            (
                backtest_id,
                data.get("ticker"),
                data.get("initial_capital"),
                data.get("position_size_pct"),
                data.get("enable_learning"),
                data.get("total_trades", 0),
                data.get("winning_trades", 0),
                data.get("losing_trades", 0),
                data.get("total_return_pct", 0),
                data.get("max_drawdown_pct", 0),
                data.get("final_portfolio_value"),
                data.get("status", "running"),
            ),
        )


def save_backtest_trade(backtest_id: str, trade: dict):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO backtest_trades
            (backtest_id, trade_date, ticker, signal, entry_price, exit_price,
             pnl_amount, pnl_pct, cumulative_pnl, portfolio_value, duration_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                backtest_id,
                trade.get("trade_date"),
                trade.get("ticker"),
                trade.get("signal"),
                trade.get("entry_price"),
                trade.get("exit_price"),
                trade.get("pnl_amount"),
                trade.get("pnl_pct"),
                trade.get("cumulative_pnl"),
                trade.get("portfolio_value"),
                trade.get("duration_seconds"),
            ),
        )


def get_backtest_run(backtest_id: str) -> dict | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM backtest_runs WHERE backtest_id = %s", (backtest_id,)).fetchone()


def get_backtest_trades(backtest_id: str) -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM backtest_trades WHERE backtest_id = %s ORDER BY trade_date",
            (backtest_id,),
        ).fetchall()


def get_backtest_history(limit: int = 20) -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT %s", (limit,)
        ).fetchall()


# --- Settings ---

def get_setting(key: str) -> str | None:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str | None):
    with get_db() as conn:
        if value is None or value == "":
            conn.execute("DELETE FROM settings WHERE key = %s", (key,))
        else:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, value),
            )


def get_all_settings() -> dict:
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


# --- Paper Trades ---

def add_paper_trade(data: dict) -> int:
    _migrate_paper_trades_columns()

    triggered = data.get("triggered_signals")
    if triggered is not None and not isinstance(triggered, str):
        triggered = json.dumps(triggered)

    regime_at_entry = data.get("regime_at_entry")
    if regime_at_entry is None:
        try:
            from backend.market_regime import get_current_regime
            regime_at_entry = get_current_regime().get("regime")
        except Exception:
            regime_at_entry = None

    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO paper_trades
            (ticker, source, strategy, direction, signal, score, confidence,
             success_probability, triggered_signals, entry_price, notes, regime_at_entry,
             stop_loss, target_1, target_2, time_horizon, analysis_task_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id""",
            (
                data.get("ticker"),
                data.get("source", "manual"),
                data.get("strategy"),
                data.get("direction", "LONG"),
                data.get("signal"),
                data.get("score"),
                data.get("confidence"),
                data.get("success_probability"),
                triggered,
                data.get("entry_price"),
                data.get("notes"),
                regime_at_entry,
                data.get("stop_loss"),
                data.get("target_1"),
                data.get("target_2"),
                data.get("time_horizon"),
                data.get("analysis_task_id"),
            ),
        )
        row = cursor.fetchone()
        if row and "id" in row:
            return row["id"]
        return cursor.lastrowid


def _migrate_paper_trades_columns():
    with get_db() as conn:
        try:
            existing = {
                r["column_name"].lower()
                for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'paper_trades'"
                ).fetchall()
            }
        except Exception:
            existing = set()

        for col, ddl in [
            ("strategy", "TEXT"),
            ("confidence", "TEXT"),
            ("triggered_signals", "TEXT"),
            ("regime_at_entry", "TEXT"),
            ("stop_loss", "REAL"),
            ("target_1", "REAL"),
            ("target_2", "REAL"),
            ("time_horizon", "TEXT"),
            ("simulated_exit_price", "REAL"),
            ("exit_reason", "TEXT"),
            ("simulated_pnl_pct", "REAL"),
            ("analysis_task_id", "TEXT"),
        ]:
            if col not in existing:
                try:
                    conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {col} {ddl}")
                except Exception:
                    pass


def list_paper_trades(status: str | None = None) -> list[dict]:
    _migrate_paper_trades_columns()
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM paper_trades WHERE status = %s ORDER BY entry_datetime DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM paper_trades ORDER BY entry_datetime DESC"
            ).fetchall()
        for d in rows:
            if d.get("triggered_signals"):
                try:
                    d["triggered_signals"] = json.loads(d["triggered_signals"])
                except Exception:
                    pass
        return rows


def update_paper_trade_prices(trade_id: int, prices: dict):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM paper_trades WHERE id = %s", (trade_id,)).fetchone()
        if not row:
            return
        entry = row["entry_price"]
        direction = row["direction"]
        multiplier = 1 if direction == "LONG" else -1

        def calc_pnl(exit_price):
            if not exit_price or not entry:
                return None
            return round(multiplier * (exit_price - entry) / entry * 100, 2)

        conn.execute(
            """UPDATE paper_trades SET
                price_1d = COALESCE(%s, price_1d),
                price_3d = COALESCE(%s, price_3d),
                price_5d = COALESCE(%s, price_5d),
                price_10d = COALESCE(%s, price_10d),
                pnl_1d_pct = COALESCE(%s, pnl_1d_pct),
                pnl_3d_pct = COALESCE(%s, pnl_3d_pct),
                pnl_5d_pct = COALESCE(%s, pnl_5d_pct),
                pnl_10d_pct = COALESCE(%s, pnl_10d_pct),
                updated_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (
                prices.get("price_1d"),
                prices.get("price_3d"),
                prices.get("price_5d"),
                prices.get("price_10d"),
                calc_pnl(prices.get("price_1d")),
                calc_pnl(prices.get("price_3d")),
                calc_pnl(prices.get("price_5d")),
                calc_pnl(prices.get("price_10d")),
                trade_id,
            ),
        )


def update_paper_trade_status(trade_id: int, status: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE paper_trades SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (status, trade_id),
        )


def save_simulated_exit(trade_id: int, exit_price: float, pnl_pct: float, reason: str):
    should_expire = reason != "held_to_present"
    status = "expired" if should_expire else "active"
    with get_db() as conn:
        conn.execute(
            """UPDATE paper_trades SET
                simulated_exit_price = %s,
                simulated_pnl_pct = %s,
                exit_reason = %s,
                status = %s,
                updated_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (exit_price, pnl_pct, reason, status, trade_id),
        )


def delete_paper_trade(trade_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM paper_trades WHERE id = %s", (trade_id,))


# --- Recommender Backtest ---

def save_recommender_backtest_row(data: dict):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO recommender_backtests
            (run_id, trade_date, ticker, signal, score, confidence, success_probability,
             entry_price, return_1d, return_3d, return_5d, return_10d, outcome_1d, outcome_5d)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                data.get("run_id"),
                data.get("trade_date"),
                data.get("ticker"),
                data.get("signal"),
                data.get("score"),
                data.get("confidence"),
                data.get("success_probability"),
                data.get("entry_price"),
                data.get("return_1d"),
                data.get("return_3d"),
                data.get("return_5d"),
                data.get("return_10d"),
                data.get("outcome_1d"),
                data.get("outcome_5d"),
            ),
        )


def get_recommender_backtest(run_id: str) -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM recommender_backtests WHERE run_id = %s ORDER BY trade_date, ticker",
            (run_id,),
        ).fetchall()


def list_recommender_backtest_runs() -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            """SELECT run_id, trade_date,
                      COUNT(*) as signals,
                      SUM(CASE WHEN outcome_5d='win' THEN 1 ELSE 0 END) as wins,
                      SUM(CASE WHEN outcome_5d='loss' THEN 1 ELSE 0 END) as losses,
                      AVG(return_5d) as avg_return_5d,
                      MAX(created_at) as created_at
               FROM recommender_backtests
               GROUP BY run_id
               ORDER BY MAX(created_at) DESC"""
        ).fetchall()
