"""FII/DII Daily Flow Tracker.

Fetches FII (Foreign Institutional Investor) and DII (Domestic Institutional Investor)
daily buy/sell data — the single biggest predictor of next-day market direction in Indian markets.

Data sources (with fallback chain):
1. NSE India official API (requires cookies + headers)
2. Moneycontrol scraper (fallback)
3. Manual entry via API (admin override)

Caches results in DB to avoid hammering external sources.
"""

import requests
import time
from datetime import datetime, date, timedelta
from typing import Optional
from backend.db import get_db


# Headers that mimic a real browser (NSE blocks most requests without these)
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/reports/fii-dii",
    "Connection": "keep-alive",
}


def _ensure_table():
    """Create fii_dii_history table if it doesn't exist."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fii_dii_history (
                date TEXT PRIMARY KEY,
                fii_buy REAL,
                fii_sell REAL,
                fii_net REAL,
                dii_buy REAL,
                dii_sell REAL,
                dii_net REAL,
                source TEXT,
                fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def _get_nse_session() -> requests.Session:
    """Create a session with NSE cookies set."""
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        # Hit the main domain first to get cookies
        session.get("https://www.nseindia.com", timeout=15)
        time.sleep(1)
    except Exception:
        pass
    return session


def fetch_from_nse() -> Optional[dict]:
    """Fetch latest FII/DII data from NSE official JSON API.

    Uses session-based cookies (not nsepython) — works from Indian IPs.
    Falls back to nsepython library if installed.

    Returns:
        Dict with date, fii_buy/sell/net, dii_buy/sell/net — or None if failed.
    """
    # Primary: direct JSON API with session cookies
    try:
        session = _get_nse_session()
        resp = session.get(
            "https://www.nseindia.com/api/fiidiiTradeReact",
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            result: dict = {
                "fii_buy": 0, "fii_sell": 0, "fii_net": 0,
                "dii_buy": 0, "dii_sell": 0, "dii_net": 0,
                "source": "nse",
            }
            for cat_key in ("FII", "FPI", "DII"):
                cat = data.get(cat_key)
                if not cat:
                    continue
                cat_name = cat_key
                buy = float(cat.get("buyValue", 0) or 0)
                sell = float(cat.get("sellValue", 0) or 0)
                net = float(cat.get("netValue", 0) or 0)
                if "FII" in cat_name or "FPI" in cat_name:
                    result["fii_buy"] = buy
                    result["fii_sell"] = sell
                    result["fii_net"] = net
                elif "DII" in cat_name:
                    result["dii_buy"] = buy
                    result["dii_sell"] = sell
                    result["dii_net"] = net
            raw_date = data.get("date", "")
            if raw_date:
                try:
                    parsed = datetime.strptime(raw_date.replace("-", " "), "%d %b %Y")
                    result["date"] = parsed.strftime("%Y-%m-%d")
                except Exception:
                    result["date"] = date.today().strftime("%Y-%m-%d")
            else:
                result["date"] = date.today().strftime("%Y-%m-%d")
            return result
    except Exception as e:
        print(f"[FII/DII] NSE JSON API failed: {e}", flush=True)

    # Fallback: nsepython library
    try:
        from nsepython import nse_fiidii

        raw = nse_fiidii()

        entries = []
        if isinstance(raw, str):
            lines = [l for l in raw.strip().split("\n") if l.strip()]
            if len(lines) < 2:
                return None

            for line in lines[1:]:
                parts = line.split()
                if parts and parts[0].isdigit():
                    parts = parts[1:]
                if len(parts) < 5:
                    continue
                try:
                    cat = parts[0]
                    date_str = parts[1]
                    buy_val = float(parts[2])
                    sell_val = float(parts[3])
                    net_val = float(parts[4])
                    entries.append({
                        "category": cat,
                        "date": date_str,
                        "buyValue": buy_val,
                        "sellValue": sell_val,
                        "netValue": net_val,
                    })
                except (ValueError, IndexError):
                    continue
        elif hasattr(raw, "to_dict"):
            entries = raw.to_dict("records")
        elif isinstance(raw, list):
            entries = raw
        else:
            return None

        if not entries:
            return None

        result = {"fii_buy": 0, "fii_sell": 0, "fii_net": 0, "dii_buy": 0, "dii_sell": 0, "dii_net": 0}
        date_str = None

        for entry in entries:
            cat = (entry.get("category") or "").upper()
            buy = float(entry.get("buyValue", 0) or 0)
            sell = float(entry.get("sellValue", 0) or 0)
            net = float(entry.get("netValue", 0) or 0)
            d = entry.get("date")
            if d and not date_str:
                date_str = d

            if "FII" in cat or "FPI" in cat:
                result["fii_buy"] = buy
                result["fii_sell"] = sell
                result["fii_net"] = net
            elif "DII" in cat:
                result["dii_buy"] = buy
                result["dii_sell"] = sell
                result["dii_net"] = net

        if date_str:
            try:
                parsed = datetime.strptime(date_str, "%d-%b-%Y")
                result["date"] = parsed.strftime("%Y-%m-%d")
            except Exception:
                result["date"] = date.today().strftime("%Y-%m-%d")
        else:
            result["date"] = date.today().strftime("%Y-%m-%d")

        result["source"] = "nse"
        return result
    except ImportError:
        pass
    except Exception as e:
        print(f"[FII/DII] nsepython fallback failed: {e}", flush=True)

    return None


def fetch_from_moneycontrol() -> Optional[dict]:
    """Fallback: scrape FII/DII data from Moneycontrol.

    Uses the FII/DII activity page which contains a structured table.
    This endpoint is less likely to geo-block than NSE.
    """
    try:
        url = "https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/index.php"
        resp = requests.get(url, headers={"User-Agent": NSE_HEADERS["User-Agent"]}, timeout=15)
        if resp.status_code != 200:
            return None

        text = resp.text

        # Look for the FII row in the data table — typical structure:
        # <td>FII</td><td>Buy Value</td><td>12,345.67</td>...
        # or the newer div-based layout with class="tblData" or "mkt_info"
        import re

        result: dict = {
            "fii_buy": 0, "fii_sell": 0, "fii_net": 0,
            "dii_buy": 0, "dii_sell": 0, "dii_net": 0,
            "source": "moneycontrol",
            "date": date.today().strftime("%Y-%m-%d"),
        }

        # Strategy: find the FII/DII table by looking for its container
        # and then extracting numbers from that region only.
        # Try to locate the section containing both FII and DII data.
        markers = ["FII", "DII", "FPI", "Institutional", "RnDTable"]
        table_start = len(text)
        table_end = 0
        for m in markers:
            idx = text.find(m)
            if idx != -1:
                table_start = min(table_start, idx)
                # Look up to 2000 chars after the first marker
                table_end = max(table_end, idx + 2000)

        if table_start >= table_end:
            return None

        table_html = text[table_start:table_end]

        # Find all ₹ Crore values (numbers with 2 decimals, possibly negative)
        values = re.findall(
            r'(?:Rs\.?|₹)?\s*([+-]?\s*[\d,]+\.\d{2})',
            table_html,
        )
        cleaned = [float(v.replace(",", "").replace(" ", "")) for v in values]

        # Filter to reasonable ranges (FII/DII in ₹ Crores: typically 0-50k)
        crores = [v for v in cleaned if 0 < v < 100000]

        if len(crores) < 4:
            # Try without the currency prefix — look for any decimal number
            all_vals = re.findall(r'([+-]?\s*[\d,]+\.\d{2})', table_html)
            cleaned_all = [float(v.replace(",", "").replace(" ", "")) for v in all_vals]
            crores = [v for v in cleaned_all if 0 < v < 100000]

        if len(crores) >= 6:
            # Expecting: FII buy, FII sell, FII net, DII buy, DII sell, DII net
            result["fii_buy"] = crores[0]
            result["fii_sell"] = crores[1]
            result["fii_net"] = crores[2]
            result["dii_buy"] = crores[3]
            result["dii_sell"] = crores[4]
            result["dii_net"] = crores[5]
        elif len(crores) >= 2:
            # Fallback: just first set of values
            result["fii_buy"] = crores[0]
            result["fii_sell"] = crores[1] if len(crores) > 1 else 0
            # If only 2 values, try to find remaining nearby
            remaining = crores[2:]
            if len(remaining) >= 4:
                result["dii_buy"] = remaining[0]
                result["dii_sell"] = remaining[1]
                result["dii_net"] = remaining[3]
            # Compute nets
            if result["fii_net"] == 0:
                result["fii_net"] = round(result["fii_buy"] - result["fii_sell"], 2)
            if result["dii_net"] == 0 and result["dii_buy"] and result["dii_sell"]:
                result["dii_net"] = round(result["dii_buy"] - result["dii_sell"], 2)
        else:
            return None

        if result["fii_net"] == 0 and result["dii_net"] == 0:
            return None

        return result
    except Exception as e:
        print(f"[FII/DII] Moneycontrol fallback failed: {e}", flush=True)
        return None


def get_today_data(force_refresh: bool = False) -> Optional[dict]:
    """Get today's FII/DII data — checks cache first, then fetches if needed."""
    _ensure_table()
    today_str = date.today().strftime("%Y-%m-%d")

    if not force_refresh:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM fii_dii_history WHERE date = %s", (today_str,)
            ).fetchone()
            if row:
                d = row
                # If fetched within last hour, use cache
                fetched = datetime.fromisoformat(d["fetched_at"])
                if (datetime.now() - fetched).total_seconds() < 3600:
                    return d

    # Fetch fresh
    data = fetch_from_nse()
    if not data:
        data = fetch_from_moneycontrol()

    if data:
        save_data(data)
        return get_data_for_date(data["date"])

    return None


def save_data(data: dict):
    """Save FII/DII data to DB."""
    _ensure_table()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO fii_dii_history
            (date, fii_buy, fii_sell, fii_net, dii_buy, dii_sell, dii_net, source, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (date) DO UPDATE SET
            fii_buy = EXCLUDED.fii_buy, fii_sell = EXCLUDED.fii_sell, fii_net = EXCLUDED.fii_net,
            dii_buy = EXCLUDED.dii_buy, dii_sell = EXCLUDED.dii_sell, dii_net = EXCLUDED.dii_net,
            source = EXCLUDED.source, fetched_at = CURRENT_TIMESTAMP""",
            (
                data.get("date"),
                data.get("fii_buy"),
                data.get("fii_sell"),
                data.get("fii_net"),
                data.get("dii_buy"),
                data.get("dii_sell"),
                data.get("dii_net"),
                data.get("source", "manual"),
            ),
        )


def manual_entry(date_str: str, fii_net: float, dii_net: float,
                 fii_buy: float = None, fii_sell: float = None,
                 dii_buy: float = None, dii_sell: float = None) -> dict:
    """Manually enter FII/DII data for a date (used when scraping fails)."""
    if fii_buy is None:
        # If only net given, estimate buy/sell as +/- net
        fii_buy = abs(fii_net) if fii_net > 0 else 0
        fii_sell = abs(fii_net) if fii_net < 0 else 0
    if dii_buy is None:
        dii_buy = abs(dii_net) if dii_net > 0 else 0
        dii_sell = abs(dii_net) if dii_net < 0 else 0

    data = {
        "date": date_str,
        "fii_buy": fii_buy,
        "fii_sell": fii_sell,
        "fii_net": fii_net,
        "dii_buy": dii_buy,
        "dii_sell": dii_sell,
        "dii_net": dii_net,
        "source": "manual",
    }
    save_data(data)
    return data


def get_data_for_date(date_str: str) -> Optional[dict]:
    """Get FII/DII data for a specific date."""
    _ensure_table()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM fii_dii_history WHERE date = %s", (date_str,)
        ).fetchone()
        return row if row else None


def get_recent_history(days: int = 10) -> list[dict]:
    """Get FII/DII data for the last N days."""
    _ensure_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM fii_dii_history ORDER BY date DESC LIMIT %s", (days,)
        ).fetchall()
        return rows


def get_market_bias() -> dict:
    """Compute market bias based on recent FII/DII flows.

    Returns a structured assessment used by the recommendation engine.
    """
    history = get_recent_history(days=5)
    if not history:
        return {
            "bias": "NEUTRAL",
            "confidence": "NONE",
            "score_adjustment": 0,
            "reasoning": "No FII/DII data available",
            "today_fii_net": None,
            "today_dii_net": None,
        }

    today = history[0]
    fii_today = today.get("fii_net") or 0
    dii_today = today.get("dii_net") or 0

    # 5-day FII trend
    fii_5d = sum((d.get("fii_net") or 0) for d in history)
    dii_5d = sum((d.get("dii_net") or 0) for d in history)

    # Determine bias
    bias = "NEUTRAL"
    confidence = "LOW"
    score_adj = 0
    reasoning_parts = []

    # Strong FII selling (>2000 Cr) — bearish
    if fii_today < -2000:
        bias = "BEARISH"
        confidence = "HIGH"
        score_adj = -1.5
        reasoning_parts.append(f"FIIs selling heavily today (Rs.{fii_today:,.0f} Cr)")
    elif fii_today < -1000:
        bias = "BEARISH"
        confidence = "MEDIUM"
        score_adj = -1.0
        reasoning_parts.append(f"FIIs net sellers today (Rs.{fii_today:,.0f} Cr)")
    elif fii_today > 2000:
        bias = "BULLISH"
        confidence = "HIGH"
        score_adj = +1.5
        reasoning_parts.append(f"FIIs buying aggressively today (+Rs.{fii_today:,.0f} Cr)")
    elif fii_today > 1000:
        bias = "BULLISH"
        confidence = "MEDIUM"
        score_adj = +1.0
        reasoning_parts.append(f"FIIs net buyers today (+Rs.{fii_today:,.0f} Cr)")

    # DII offset
    if bias == "BEARISH" and dii_today > abs(fii_today) * 0.7:
        # DIIs absorbing the FII selling
        bias = "MIXED"
        score_adj = score_adj * 0.5  # reduce penalty
        reasoning_parts.append(f"DIIs absorbing some selling (+Rs.{dii_today:,.0f} Cr)")
    elif bias == "BULLISH" and dii_today < -abs(fii_today) * 0.5:
        bias = "MIXED"
        score_adj = score_adj * 0.5
        reasoning_parts.append(f"But DIIs selling (Rs.{dii_today:,.0f} Cr)")

    # 5-day trend
    if fii_5d < -5000:
        reasoning_parts.append(f"FIIs sold Rs.{abs(fii_5d):,.0f} Cr over 5 days — sustained outflow")
        if bias == "NEUTRAL":
            bias = "BEARISH"
            confidence = "MEDIUM"
            score_adj = -0.5
    elif fii_5d > 5000:
        reasoning_parts.append(f"FIIs bought Rs.{fii_5d:,.0f} Cr over 5 days — sustained inflow")
        if bias == "NEUTRAL":
            bias = "BULLISH"
            confidence = "MEDIUM"
            score_adj = +0.5

    if not reasoning_parts:
        reasoning_parts.append("FII/DII flows are neutral today")

    return {
        "bias": bias,
        "confidence": confidence,
        "score_adjustment": round(score_adj, 2),
        "reasoning": ". ".join(reasoning_parts),
        "today_fii_net": round(fii_today, 0),
        "today_dii_net": round(dii_today, 0),
        "fii_5d_net": round(fii_5d, 0),
        "dii_5d_net": round(dii_5d, 0),
        "data_date": today.get("date"),
    }
