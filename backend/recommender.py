"""Unified Recommendation Engine — continuous scoring, progressive streaming.

Every stock gets a score from continuous factor contributions. ALL stocks are
ranked and returned — no NEUTRAL filtering. Results stream progressively via SSE.
"""

import asyncio
import json
import math
import gc
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
from typing import AsyncGenerator

import numpy as np
import pandas as pd

from backend.scanner import NIFTY_50, NIFTY_100, BSE_250, UNIVERSES
from tradingagents.dataflows.interface import route_to_vendor


# Score caps per factor (continuous max contribution)
_FACTOR_CAPS = {
    "gap": 3.0,
    "volume": 3.0,
    "breakout": 3.0,
    "support_resistance": 3.0,
    "rsi": 2.0,
    "trend": 3.0,
    "momentum": 2.0,
    "cyclical": 2.0,
}


# Historical win rates (baseline — will be overridden by live performance data if available)
DEFAULT_WEIGHTS = {
    "gap_up_filled": 1.5,
    "gap_down_filled": 1.5,
    "gap_up_open": -0.5,
    "gap_down_open": -0.5,
    "volume_bullish": 2.0,
    "volume_bearish": -2.0,
    "breakout_vol_confirmed": 3.0,
    "breakout_weak": 1.0,
    "near_support": 2.0,
    "near_resistance": -1.5,
    "breakdown_support": -2.5,
    "cyclical_bullish": 1.5,
    "cyclical_bearish": -1.5,
    "rsi_oversold": 1.5,
    "rsi_overbought": -1.0,
    "uptrend_strong": 1.0,
    "downtrend_strong": -1.0,
}

_ACTIVE_WEIGHTS: dict[str, float] = dict(DEFAULT_WEIGHTS)
_ACTIVE_REGIME: str | None = None


def _refresh_active_weights() -> None:
    global _ACTIVE_WEIGHTS, _ACTIVE_REGIME
    try:
        from backend.signal_performance import get_active_weights_for_regime
        current_regime = None
        try:
            from backend.market_regime import get_current_regime
            current_regime = (get_current_regime() or {}).get("regime")
        except Exception:
            pass
        _ACTIVE_REGIME = current_regime
        _ACTIVE_WEIGHTS = get_active_weights_for_regime(current_regime)
    except Exception:
        _ACTIVE_WEIGHTS = dict(DEFAULT_WEIGHTS)
        _ACTIVE_REGIME = None


def _compute_rsi(closes: np.ndarray, period: int = 14) -> float:
    deltas = np.diff(closes)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    if down == 0:
        return 100
    rs = up / down
    return 100 - 100 / (1 + rs)


def _analyze_stock(ticker: str, data_window_days: int = 60) -> dict | None:
    """Analyze a single stock with continuous scoring.

    Returns a dict for ALL stocks that have basic price data. No stock is
    filtered out as NEUTRAL — every stock gets a score and ranking.
    """
    try:
        symbol = f"{ticker}.NS"
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=data_window_days)).strftime("%Y-%m-%d")
        csv_str = route_to_vendor("get_stock_data", ticker, start, end)
        hist = pd.read_csv(StringIO(csv_str), comment="#", parse_dates=["Date"])
        if hist.empty or len(hist) < 10:
            return None

        closes = hist["Close"].values
        highs = hist["High"].values
        lows = hist["Low"].values
        volumes = hist["Volume"].values

        current_close = float(closes[-1])
        current_open = float(hist.iloc[-1]["Open"])
        current_high = float(highs[-1])
        current_low = float(lows[-1])
        prev_close = float(closes[-2])
        current_volume = float(volumes[-1])
        avg_volume = float(np.mean(volumes[-20:-1])) if len(volumes) > 20 else float(np.mean(volumes[:-1]))
        price_change_day = (current_close - prev_close) / prev_close * 100

        signals: list[dict] = []
        total_score = 0.0
        recent_high = None
        recent_low = None

        # 1. GAP (continuous proportional)
        gap_pct = (current_open - prev_close) / prev_close * 100
        gap_score = max(min(gap_pct * 0.35, _FACTOR_CAPS["gap"]), -_FACTOR_CAPS["gap"])
        if abs(gap_pct) >= 0.5:
            signals.append({
                "type": "Gap",
                "direction": "BULLISH" if gap_pct > 0 else "BEARISH",
                "value": f"{gap_pct:+.2f}%",
                "weight": round(gap_score, 2),
            })
        total_score += gap_score

        # 2. VOLUME (logarithmic continuous)
        vol_score = 0.0
        if avg_volume > 0 and current_volume > 0:
            vol_ratio = current_volume / avg_volume
            if vol_ratio > 1.0:
                vol_score = math.log2(vol_ratio) * 0.75
            vol_score = max(min(vol_score, _FACTOR_CAPS["volume"]), -_FACTOR_CAPS["volume"])
            if abs(vol_ratio - 1) >= 0.5:
                signals.append({
                    "type": "Volume",
                    "direction": "BULLISH" if price_change_day > 0 else "BEARISH",
                    "value": f"{vol_ratio:.1f}x avg",
                    "weight": round(vol_score, 2),
                })
        total_score += vol_score

        # 3. BREAKOUT / BREAKDOWN (continuous)
        breakout_score = 0.0
        if len(closes) >= 21:
            n_day_high = float(np.max(highs[-21:-1]))
            n_day_low = float(np.min(lows[-21:-1]))
            if current_high > n_day_high:
                breakout_pct = (current_close - n_day_high) / n_day_high * 100
                breakout_score = min(breakout_pct * 10, _FACTOR_CAPS["breakout"])
                signals.append({
                    "type": "Breakout",
                    "direction": "BULLISH",
                    "value": f"+{breakout_pct:.2f}% above 20d high",
                    "weight": round(breakout_score, 2),
                })
            elif current_low < n_day_low:
                breakdown_pct = (n_day_low - current_low) / n_day_low * 100
                breakout_score = -min(breakdown_pct * 10, _FACTOR_CAPS["breakout"])
                signals.append({
                    "type": "Breakdown",
                    "direction": "BEARISH",
                    "value": f"-{breakdown_pct:.2f}% below 20d low",
                    "weight": round(breakout_score, 2),
                })
        total_score += breakout_score

        # 4. SUPPORT / RESISTANCE PROXIMITY (inverse-distance continuous)
        sr_score = 0.0
        if len(closes) >= 60:
            recent_high = float(np.max(highs[-60:]))
            recent_low = float(np.min(lows[-60:]))
            distance_to_high = (recent_high - current_close) / current_close * 100
            distance_to_low = (current_close - recent_low) / current_close * 100

            support_val = 0.0
            resistance_val = 0.0
            if 0 < distance_to_low < 5:
                support_val = 1.0 / max(distance_to_low, 0.1)
            if 0 < distance_to_high < 5:
                resistance_val = -1.0 / max(distance_to_high, 0.1)

            if support_val >= 0.5:
                signals.append({
                    "type": "Near Support",
                    "direction": "BULLISH",
                    "value": f"{distance_to_low:.1f}% above 60d low",
                    "weight": round(support_val, 2),
                })
                sr_score += support_val
            elif resistance_val <= -0.5:
                signals.append({
                    "type": "Near Resistance",
                    "direction": "BEARISH",
                    "value": f"{distance_to_high:.1f}% below 60d high",
                    "weight": round(resistance_val, 2),
                })
                sr_score += resistance_val

            sr_score = max(min(sr_score, _FACTOR_CAPS["support_resistance"]), -_FACTOR_CAPS["support_resistance"])
        total_score += sr_score

        # 5. RSI (continuous deviation from 50)
        rsi = None
        rsi_score = 0.0
        if len(closes) >= 14:
            rsi = _compute_rsi(closes[-15:])
            rsi_score = (50 - rsi) / 20
            rsi_score = max(min(rsi_score, _FACTOR_CAPS["rsi"]), -_FACTOR_CAPS["rsi"])
            if abs(rsi_score) >= 0.3:
                if rsi < 35:
                    label = "RSI Oversold"
                elif rsi > 65:
                    label = "RSI Overbought"
                else:
                    label = f"RSI {'Bullish' if rsi < 50 else 'Bearish'}"
                signals.append({
                    "type": label,
                    "direction": "BULLISH" if rsi < 50 else "BEARISH",
                    "value": f"RSI {rsi:.1f}",
                    "weight": round(rsi_score, 2),
                })
            total_score += rsi_score

        # 6. TREND (SMA alignment — continuous)
        trend_score = 0.0
        if len(closes) >= 50:
            sma50 = float(np.mean(closes[-50:]))
            sma50_score = (current_close / sma50 - 1) * 3
            sma50_score = max(min(sma50_score, 2), -2)

            sma200_score = 0.0
            if len(closes) >= 200:
                sma200 = float(np.mean(closes[-200:]))
                sma200_score = (current_close / sma200 - 1) * 2
                sma200_score = max(min(sma200_score, 2), -2)

            trend_score = sma50_score + sma200_score * 0.5
            trend_score = max(min(trend_score, _FACTOR_CAPS["trend"]), -_FACTOR_CAPS["trend"])
            if abs(trend_score) >= 0.3:
                signals.append({
                    "type": "Trend",
                    "direction": "BULLISH" if trend_score > 0 else "BEARISH",
                    "value": f"Score {trend_score:+.1f}",
                    "weight": round(trend_score, 2),
                })
        total_score += trend_score

        # 7. MOMENTUM (5-day return)
        momentum_score = 0.0
        if len(closes) >= 6:
            ret_5d = (current_close / closes[-5] - 1) * 100
            momentum_score = ret_5d * 0.3
            momentum_score = max(min(momentum_score, _FACTOR_CAPS["momentum"]), -_FACTOR_CAPS["momentum"])
            if abs(ret_5d) >= 0.5:
                signals.append({
                    "type": "Momentum",
                    "direction": "BULLISH" if ret_5d > 0 else "BEARISH",
                    "value": f"{ret_5d:+.2f}% 5-day",
                    "weight": round(momentum_score, 2),
                })
        total_score += momentum_score

        # 8. CYCLICAL (monthly pattern — continuous)
        cyclical_score = 0.0
        current_month = datetime.now().month
        hist["Month"] = hist["Date"].dt.month
        hist["MonthlyReturn"] = hist["Close"].pct_change()
        month_data = hist[hist["Month"] == current_month]["MonthlyReturn"].dropna()
        if len(month_data) > 5:
            avg_month_return = float(month_data.mean() * 100)
            cyclical_score = avg_month_return * 2
            cyclical_score = max(min(cyclical_score, _FACTOR_CAPS["cyclical"]), -_FACTOR_CAPS["cyclical"])
            if abs(avg_month_return) >= 0.3:
                signals.append({
                    "type": "Cyclical",
                    "direction": "BULLISH" if avg_month_return > 0 else "BEARISH",
                    "value": f"{avg_month_return:+.2f}% avg",
                    "weight": round(cyclical_score, 2),
                })
        total_score += cyclical_score
        hist.drop(columns=["Month", "MonthlyReturn"], inplace=True, errors="ignore")

        # === CLASSIFICATION (used for display buckets) ===
        if total_score >= 4.0:
            direction = "STRONG BUY"
        elif total_score >= 1.5:
            direction = "BUY"
        elif total_score <= -4.0:
            direction = "STRONG SELL"
        elif total_score <= -1.5:
            direction = "SELL"
        else:
            direction = "NEUTRAL"

        bullish_signals = [s for s in signals if s["direction"] == "BULLISH"]
        bearish_signals = [s for s in signals if s["direction"] == "BEARISH"]
        aligned_count = max(len(bullish_signals), len(bearish_signals))
        confidence = "HIGH" if aligned_count >= 4 else ("MEDIUM" if aligned_count >= 2 else "LOW")

        abs_score = abs(total_score)
        base_prob = 50.0
        score_edge = min(abs_score * 5, 30)
        alignment_bonus = min(aligned_count * 2, 15)
        success_probability = round(min(base_prob + score_edge + alignment_bonus, 85), 0)
        if abs_score < 0.5:
            success_probability = 50

        return {
            "ticker": ticker,
            "symbol": symbol,
            "price": round(current_close, 2),
            "change_pct": round(price_change_day, 2),
            "rsi": round(rsi, 1) if rsi else None,
            "score": round(total_score, 2),
            "direction": direction,
            "confidence": confidence,
            "success_probability": int(success_probability),
            "signals": signals,
            "bullish_signal_count": len(bullish_signals),
            "bearish_signal_count": len(bearish_signals),
            "near_support": round(recent_low, 2) if recent_low is not None else None,
            "near_resistance": round(recent_high, 2) if recent_high is not None else None,
        }
    except Exception as e:
        return None


# ── Post-analysis filters (unchanged logic) ──────────────────────────


def _apply_market_bias(result: dict, bias: dict) -> dict:
    if not bias or bias.get("score_adjustment", 0) == 0:
        return result
    adj = bias["score_adjustment"]
    new_score = round(result["score"] + adj, 2)
    fii_signal = {
        "type": f"FII/DII Flow ({bias['bias']})",
        "direction": "BULLISH" if adj > 0 else ("BEARISH" if adj < 0 else "NEUTRAL"),
        "value": bias["reasoning"],
        "weight": adj,
    }
    result["signals"] = list(result.get("signals", [])) + [fii_signal]
    if adj > 0:
        result["bullish_signal_count"] = result.get("bullish_signal_count", 0) + 1
    elif adj < 0:
        result["bearish_signal_count"] = result.get("bearish_signal_count", 0) + 1

    if new_score >= 4.0:
        result["direction"] = "STRONG BUY"
    elif new_score >= 1.5:
        result["direction"] = "BUY"
    elif new_score <= -4.0:
        result["direction"] = "STRONG SELL"
    elif new_score <= -1.5:
        result["direction"] = "SELL"
    else:
        result["direction"] = "NEUTRAL"

    abs_score = abs(new_score)
    aligned = max(result.get("bullish_signal_count", 0), result.get("bearish_signal_count", 0))
    score_edge = min(abs_score * 5, 30)
    alignment_bonus = min(aligned * 2, 15)
    success_probability = round(min(50 + score_edge + alignment_bonus, 85), 0)
    if abs_score < 0.5:
        success_probability = 50

    result["score"] = new_score
    result["success_probability"] = int(success_probability)
    result["market_bias_applied"] = bias["bias"]
    return result


def _apply_concentration_filter(result: dict, concentration_check: dict) -> dict:
    if not concentration_check:
        return result
    sector = concentration_check.get("sector", "Other")
    result["sector"] = sector
    adj = concentration_check.get("score_adjustment", 0)
    if adj == 0:
        return result
    new_score = round(result["score"] + adj, 2)
    warnings = concentration_check.get("warnings", [])
    conc_signal = {
        "type": f"Sector Concentration ({sector})",
        "direction": "BEARISH",
        "value": "; ".join(warnings) if warnings else "Approaching sector limit",
        "weight": adj,
    }
    result["signals"] = list(result.get("signals", [])) + [conc_signal]
    result["bearish_signal_count"] = result.get("bearish_signal_count", 0) + 1
    result["concentration_warning"] = "; ".join(warnings) if warnings else None
    result["concentration_breach"] = concentration_check.get("would_breach", False)

    if new_score >= 4.0:
        result["direction"] = "STRONG BUY"
    elif new_score >= 1.5:
        result["direction"] = "BUY"
    elif new_score <= -4.0:
        result["direction"] = "STRONG SELL"
    elif new_score <= -1.5:
        result["direction"] = "SELL"
    else:
        result["direction"] = "NEUTRAL"

    abs_score = abs(new_score)
    aligned = max(result.get("bullish_signal_count", 0), result.get("bearish_signal_count", 0))
    score_edge = min(abs_score * 5, 30)
    alignment_bonus = min(aligned * 2, 15)
    success_probability = round(min(50 + score_edge + alignment_bonus, 85), 0)
    if abs_score < 0.5:
        success_probability = 50

    result["score"] = new_score
    result["success_probability"] = int(success_probability)
    return result


def _apply_event_filter(result: dict, event_filter: dict) -> dict:
    if not event_filter or not event_filter.get("has_event"):
        return result
    adj = event_filter.get("score_adjustment", 0)
    if adj == 0:
        return result
    new_score = round(result["score"] + adj, 2)
    warning = event_filter.get("warning") or "Upcoming event"
    event_signal = {
        "type": f"Event Risk ({warning})",
        "direction": "BEARISH",
        "value": warning,
        "weight": adj,
    }
    result["signals"] = list(result.get("signals", [])) + [event_signal]
    result["bearish_signal_count"] = result.get("bearish_signal_count", 0) + 1
    result["event_warning"] = warning
    result["upcoming_events"] = event_filter.get("events", [])

    if new_score >= 4.0:
        result["direction"] = "STRONG BUY"
    elif new_score >= 1.5:
        result["direction"] = "BUY"
    elif new_score <= -4.0:
        result["direction"] = "STRONG SELL"
    elif new_score <= -1.5:
        result["direction"] = "SELL"
    else:
        result["direction"] = "NEUTRAL"

    abs_score = abs(new_score)
    aligned = max(result.get("bullish_signal_count", 0), result.get("bearish_signal_count", 0))
    score_edge = min(abs_score * 5, 30)
    alignment_bonus = min(aligned * 2, 15)
    success_probability = round(min(50 + score_edge + alignment_bonus, 85), 0)
    if abs_score < 0.5:
        success_probability = 50

    result["score"] = new_score
    result["success_probability"] = int(success_probability)
    return result


# ── Sync entry-point (backward compatible) ───────────────────────────


def recommend(
    universe: str = "nifty100",
    min_signals: int = 2,
    apply_market_bias: bool = True,
    apply_event_filter: bool = True,
    apply_concentration_check: bool = True,
    total_capital: float = 500000,
) -> dict:
    """Run recommendation engine across a stock universe.

    Returns ALL stocks ranked by score. The ``min_signals`` parameter is kept
    for API backward compatibility but does NOT filter stocks — all stocks are
    in ``results`` regardless.
    """
    _refresh_active_weights()

    stocks = UNIVERSES.get(universe, NIFTY_100)
    all_results: list[dict] = []

    market_bias = None
    if apply_market_bias:
        try:
            from backend.fii_dii import get_market_bias
            market_bias = get_market_bias()
        except Exception as e:
            print(f"[Recommender] FII/DII fetch failed: {e}", flush=True)

    today_market_events: list = []
    if apply_event_filter:
        try:
            from backend.calendar_data import get_market_events_in_range
            today = date.today()
            today_market_events = get_market_events_in_range(today, today + timedelta(days=2))
        except Exception as e:
            print(f"[Recommender] Calendar fetch failed: {e}", flush=True)

    concentration_summary = None
    if apply_concentration_check:
        try:
            from backend.concentration import get_concentration_summary
            concentration_summary = get_concentration_summary()
        except Exception as e:
            print(f"[Recommender] Concentration check failed: {e}", flush=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(_analyze_stock, ticker): ticker for ticker in stocks}
        for f in as_completed(futures):
            result = f.result()
            if result is None:
                continue
            if market_bias:
                result = _apply_market_bias(result, market_bias)
            if apply_event_filter:
                try:
                    from backend.calendar_data import get_event_filter_for_ticker
                    event_filter = get_event_filter_for_ticker(result["ticker"], days_ahead=2)
                    if event_filter.get("has_event"):
                        result = _apply_event_filter(result, event_filter)
                except Exception:
                    pass
            if apply_concentration_check and result.get("direction") in ("STRONG BUY", "BUY"):
                try:
                    from backend.concentration import check_new_trade_concentration
                    conc_check = check_new_trade_concentration(
                        result["ticker"],
                        proposed_position_value=total_capital * 0.1,
                        total_capital=total_capital,
                    )
                    result = _apply_concentration_filter(result, conc_check)
                except Exception:
                    pass
            all_results.append(result)

    all_results.sort(key=lambda x: -x["score"])

    strong_buys = [r for r in all_results if r["direction"] == "STRONG BUY"]
    buys = [r for r in all_results if r["direction"] == "BUY"]
    sells = [r for r in all_results if r["direction"] == "SELL"]
    strong_sells = [r for r in all_results if r["direction"] == "STRONG SELL"]

    regime_weight_count = 0
    try:
        from backend.signal_performance import get_regime_weights
        if _ACTIVE_REGIME:
            regime_weight_count = len(get_regime_weights().get(_ACTIVE_REGIME, {}))
    except Exception:
        pass

    result = {
        "universe": universe,
        "total_analyzed": len(stocks),
        "total_with_signals": len(all_results),
        "market_bias": market_bias,
        "today_market_events": today_market_events,
        "concentration_summary": concentration_summary,
        "active_regime": _ACTIVE_REGIME,
        "regime_weight_overrides_active": regime_weight_count,
        "results": all_results,
        "strong_buys": strong_buys[:20],
        "buys": buys[:20],
        "sells": sells[:20],
        "strong_sells": strong_sells[:20],
    }

    try:
        from backend.shadow_trades import record_shadow_trades_from_recommendations
        record_shadow_trades_from_recommendations(result)
    except Exception as e:
        print(f"[Recommender] shadow recording failed: {e}", flush=True)

    gc.collect()
    return result


# ── Async / SSE entry-point ──────────────────────────────────────────


async def recommend_stream(
    universe: str = "nifty100",
    apply_market_bias: bool = True,
    apply_event_filter: bool = True,
    apply_concentration_check: bool = True,
    total_capital: float = 500000,
) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted events.

    Event types:
      - ``metadata``: market_bias + today_market_events (one event at start)
      - ``result``: individual stock result as each completes
      - ``progress``: ``{done, total}`` heartbeat every 5 stocks
      - ``complete``: final sorted response with all buckets
    """
    _refresh_active_weights()

    stocks = UNIVERSES.get(universe, NIFTY_100)

    # 1. Fetch global data (offload sync calls)
    market_bias = None
    if apply_market_bias:
        try:
            from backend.fii_dii import get_market_bias
            market_bias = await asyncio.to_thread(get_market_bias)
        except Exception:
            pass

    today_market_events: list = []
    if apply_event_filter:
        try:
            from backend.calendar_data import get_market_events_in_range
            today = date.today()
            today_market_events = await asyncio.to_thread(
                get_market_events_in_range, today, today + timedelta(days=2)
            )
        except Exception:
            pass

    concentration_summary = None
    if apply_concentration_check:
        try:
            from backend.concentration import get_concentration_summary
            concentration_summary = await asyncio.to_thread(get_concentration_summary)
        except Exception:
            pass

    yield f"event: metadata\ndata: {json.dumps({'bias': market_bias, 'events': today_market_events})}\n\n"

    # 2. Analyze stocks with concurrency cap
    sem = asyncio.Semaphore(2)
    all_results: list[dict] = []

    async def _analyze_one(t: str) -> dict | None:
        async with sem:
            return await asyncio.to_thread(_analyze_stock, t)

    tasks = [_analyze_one(t) for t in stocks]
    done = 0
    total = len(tasks)

    for coro in asyncio.as_completed(tasks):
        result = await coro
        done += 1
        if result is not None:
            if market_bias:
                result = _apply_market_bias(result, market_bias)
            if apply_event_filter:
                try:
                    from backend.calendar_data import get_event_filter_for_ticker
                    evt = await asyncio.to_thread(
                        get_event_filter_for_ticker, result["ticker"], days_ahead=2
                    )
                    if evt.get("has_event"):
                        result = _apply_event_filter(result, evt)
                except Exception:
                    pass
            if apply_concentration_check and result.get("direction") in ("STRONG BUY", "BUY"):
                try:
                    from backend.concentration import check_new_trade_concentration
                    conc = await asyncio.to_thread(
                        check_new_trade_concentration,
                        result["ticker"],
                        proposed_position_value=total_capital * 0.1,
                        total_capital=total_capital,
                    )
                    result = _apply_concentration_filter(result, conc)
                except Exception:
                    pass

            all_results.append(result)
            yield f"event: result\ndata: {json.dumps(result, default=str)}\n\n"

        if done % 5 == 0 or done == total:
            yield f"event: progress\ndata: {json.dumps({'done': done, 'total': total})}\n\n"

    # 3. Build final sorted response
    all_results.sort(key=lambda x: -x["score"])
    strong_buys = [r for r in all_results if r["direction"] == "STRONG BUY"]
    buys = [r for r in all_results if r["direction"] == "BUY"]
    sells = [r for r in all_results if r["direction"] == "SELL"]
    strong_sells = [r for r in all_results if r["direction"] == "STRONG SELL"]

    regime_weight_count = 0
    try:
        from backend.signal_performance import get_regime_weights
        if _ACTIVE_REGIME:
            regime_weight_count = len(get_regime_weights().get(_ACTIVE_REGIME, {}))
    except Exception:
        pass

    final = {
        "universe": universe,
        "total_analyzed": len(stocks),
        "total_with_signals": len(all_results),
        "market_bias": market_bias,
        "today_market_events": today_market_events,
        "concentration_summary": concentration_summary,
        "active_regime": _ACTIVE_REGIME,
        "regime_weight_overrides_active": regime_weight_count,
        "results": all_results,
        "strong_buys": strong_buys[:20],
        "buys": buys[:20],
        "sells": sells[:20],
        "strong_sells": strong_sells[:20],
    }

    try:
        from backend.shadow_trades import record_shadow_trades_from_recommendations
        await asyncio.to_thread(record_shadow_trades_from_recommendations, final)
    except Exception:
        pass

    gc.collect()
    yield f"event: complete\ndata: {json.dumps(final, default=str)}\n\n"
