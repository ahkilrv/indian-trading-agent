"""FII/DII F&O Open Interest Tracker.

Fetches FII and DII participant-wise open interest data from NSE archives
(Futures & Options segment). This shows institutional positioning in index
futures, stock futures, index calls, and index puts.

Data source: NSE archives CSV (nsearchives.nseindia.com/content/nsccl/)
"""

import csv
import io
import re
import time
from datetime import datetime, date, timedelta
from typing import Optional

import requests

from backend.db import get_db


NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/reports/fii-dii",
}

FAO_ARCHIVE_URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{datepart}.csv"
FAO_ARCHIVE_URL_B = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{datepart}_b.csv"

MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def _ensure_table():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fii_dii_fao (
                date TEXT PRIMARY KEY,
                fii_idx_fut_long INTEGER DEFAULT 0,
                fii_idx_fut_short INTEGER DEFAULT 0,
                fii_idx_fut_net INTEGER DEFAULT 0,
                fii_stk_fut_long INTEGER DEFAULT 0,
                fii_stk_fut_short INTEGER DEFAULT 0,
                fii_stk_fut_net INTEGER DEFAULT 0,
                fii_idx_call_long INTEGER DEFAULT 0,
                fii_idx_call_short INTEGER DEFAULT 0,
                fii_idx_call_net INTEGER DEFAULT 0,
                fii_idx_put_long INTEGER DEFAULT 0,
                fii_idx_put_short INTEGER DEFAULT 0,
                fii_idx_put_net INTEGER DEFAULT 0,
                dii_idx_fut_long INTEGER DEFAULT 0,
                dii_idx_fut_short INTEGER DEFAULT 0,
                dii_idx_fut_net INTEGER DEFAULT 0,
                dii_stk_fut_long INTEGER DEFAULT 0,
                dii_stk_fut_short INTEGER DEFAULT 0,
                dii_stk_fut_net INTEGER DEFAULT 0,
                pcr REAL DEFAULT 1.0,
                sentiment_score REAL DEFAULT 50.0,
                source TEXT DEFAULT 'nse',
                fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def _get_nse_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get("https://www.nseindia.com/", timeout=10)
        time.sleep(0.5)
    except Exception:
        pass
    return session


def _date_to_nse_format(date_str: str) -> Optional[str]:
    parts = date_str.split("-")
    if len(parts) != 3:
        return None
    day, mon, year = parts
    day = day.zfill(2)
    month_num = MONTH_MAP.get(mon)
    if not month_num:
        return None
    return f"{day}{month_num}{year}"


def parse_fao_csv(csv_text: str) -> dict:
    result = {
        "fii_idx_fut_long": 0, "fii_idx_fut_short": 0, "fii_idx_fut_net": 0,
        "fii_stk_fut_long": 0, "fii_stk_fut_short": 0, "fii_stk_fut_net": 0,
        "fii_idx_call_long": 0, "fii_idx_call_short": 0, "fii_idx_call_net": 0,
        "fii_idx_put_long": 0, "fii_idx_put_short": 0, "fii_idx_put_net": 0,
        "dii_idx_fut_long": 0, "dii_idx_fut_short": 0, "dii_idx_fut_net": 0,
        "dii_stk_fut_long": 0, "dii_stk_fut_short": 0, "dii_stk_fut_net": 0,
        "pcr": 1.0,
        "sentiment_score": 50.0,
    }

    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        if len(row) < 9:
            continue
        client_type = row[0].strip().upper()

        def _int(val):
            try:
                return int(re.sub(r"[^\d\-]", "", str(val).strip())) if val else 0
            except (ValueError, TypeError):
                return 0

        is_fii = "FII" in client_type
        is_dii = "DII" in client_type
        if not is_fii and not is_dii:
            continue

        prefix = "fii" if is_fii else "dii"

        result[f"{prefix}_idx_fut_long"] = _int(row[1])
        result[f"{prefix}_idx_fut_short"] = _int(row[2])
        result[f"{prefix}_stk_fut_long"] = _int(row[3])
        result[f"{prefix}_stk_fut_short"] = _int(row[4])
        result[f"{prefix}_idx_call_long"] = _int(row[5])
        result[f"{prefix}_idx_put_long"] = _int(row[6])
        result[f"{prefix}_idx_call_short"] = _int(row[7])
        result[f"{prefix}_idx_put_short"] = _int(row[8])

    result["fii_idx_fut_net"] = result["fii_idx_fut_long"] - result["fii_idx_fut_short"]
    result["fii_stk_fut_net"] = result["fii_stk_fut_long"] - result["fii_stk_fut_short"]
    result["fii_idx_call_net"] = result["fii_idx_call_long"] - result["fii_idx_call_short"]
    result["fii_idx_put_net"] = result["fii_idx_put_long"] - result["fii_idx_put_short"]
    result["dii_idx_fut_net"] = result["dii_idx_fut_long"] - result["dii_idx_fut_short"]
    result["dii_stk_fut_net"] = result["dii_stk_fut_long"] - result["dii_stk_fut_short"]

    call_short = result["fii_idx_call_short"]
    put_short = result["fii_idx_put_short"]
    if call_short > 0:
        result["pcr"] = round(put_short / call_short, 2)
    else:
        result["pcr"] = 1.0

    sentiment = 50.0
    sentiment += max(-15, min(15, result["fii_idx_fut_net"] / 10000))
    if result["pcr"] > 1.3:
        sentiment -= 8
    elif result["pcr"] > 1.1:
        sentiment -= 4
    if result["pcr"] < 0.7:
        sentiment += 8
    elif result["pcr"] < 0.9:
        sentiment += 4
    sentiment = max(5, min(100, round(sentiment, 1)))
    result["sentiment_score"] = sentiment

    return result


def fetch_fao_csv(date_str: str, session: Optional[requests.Session] = None) -> Optional[str]:
    datepart = _date_to_nse_format(date_str)
    if not datepart:
        return None

    if session is None:
        session = _get_nse_session()

    urls = [
        FAO_ARCHIVE_URL.format(datepart=datepart),
        FAO_ARCHIVE_URL_B.format(datepart=datepart),
    ]

    for url in urls:
        try:
            resp = session.get(url, timeout=20)
            if resp.status_code == 200 and len(resp.text.strip()) > 0:
                return resp.text
        except requests.RequestException:
            continue

    return None


def save_fao_data(date_str: str, data: dict):
    _ensure_table()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO fii_dii_fao
             (date, fii_idx_fut_long, fii_idx_fut_short, fii_idx_fut_net,
              fii_stk_fut_long, fii_stk_fut_short, fii_stk_fut_net,
              fii_idx_call_long, fii_idx_call_short, fii_idx_call_net,
              fii_idx_put_long, fii_idx_put_short, fii_idx_put_net,
              dii_idx_fut_long, dii_idx_fut_short, dii_idx_fut_net,
              dii_stk_fut_long, dii_stk_fut_short, dii_stk_fut_net,
              pcr, sentiment_score, source)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
             ON CONFLICT (date) DO UPDATE SET
             fii_idx_fut_long = EXCLUDED.fii_idx_fut_long,
             fii_idx_fut_short = EXCLUDED.fii_idx_fut_short,
             fii_idx_fut_net = EXCLUDED.fii_idx_fut_net,
             fii_stk_fut_long = EXCLUDED.fii_stk_fut_long,
             fii_stk_fut_short = EXCLUDED.fii_stk_fut_short,
             fii_stk_fut_net = EXCLUDED.fii_stk_fut_net,
             fii_idx_call_long = EXCLUDED.fii_idx_call_long,
             fii_idx_call_short = EXCLUDED.fii_idx_call_short,
             fii_idx_call_net = EXCLUDED.fii_idx_call_net,
             fii_idx_put_long = EXCLUDED.fii_idx_put_long,
             fii_idx_put_short = EXCLUDED.fii_idx_put_short,
             fii_idx_put_net = EXCLUDED.fii_idx_put_net,
             dii_idx_fut_long = EXCLUDED.dii_idx_fut_long,
             dii_idx_fut_short = EXCLUDED.dii_idx_fut_short,
             dii_idx_fut_net = EXCLUDED.dii_idx_fut_net,
             dii_stk_fut_long = EXCLUDED.dii_stk_fut_long,
             dii_stk_fut_short = EXCLUDED.dii_stk_fut_short,
             dii_stk_fut_net = EXCLUDED.dii_stk_fut_net,
             pcr = EXCLUDED.pcr,
             sentiment_score = EXCLUDED.sentiment_score,
             source = EXCLUDED.source""",
            (
                date_str,
                data["fii_idx_fut_long"], data["fii_idx_fut_short"], data["fii_idx_fut_net"],
                data["fii_stk_fut_long"], data["fii_stk_fut_short"], data["fii_stk_fut_net"],
                data["fii_idx_call_long"], data["fii_idx_call_short"], data["fii_idx_call_net"],
                data["fii_idx_put_long"], data["fii_idx_put_short"], data["fii_idx_put_net"],
                data["dii_idx_fut_long"], data["dii_idx_fut_short"], data["dii_idx_fut_net"],
                data["dii_stk_fut_long"], data["dii_stk_fut_short"], data["dii_stk_fut_net"],
                data["pcr"], data["sentiment_score"],
                data.get("source", "nse"),
            ),
        )


def fetch_and_save_fao(date_str: str) -> Optional[dict]:
    csv_text = fetch_fao_csv(date_str)
    if not csv_text:
        return None

    parsed = parse_fao_csv(csv_text)

    has_data = any(
        parsed[k] != 0
        for k in [
            "fii_idx_fut_long", "fii_stk_fut_long",
            "fii_idx_call_long", "fii_idx_put_long",
        ]
    )
    if not has_data:
        return None

    save_fao_data(date_str, parsed)
    parsed["date"] = date_str
    parsed["source"] = "nse"
    return parsed


def get_fao_for_date(date_str: str) -> Optional[dict]:
    _ensure_table()
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM fii_dii_fao WHERE date = %s", (date_str,)
        ).fetchone()


def get_recent_fao(days: int = 10) -> list[dict]:
    _ensure_table()
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM fii_dii_fao ORDER BY date DESC LIMIT %s", (days,)
        ).fetchall()


def get_available_dates() -> list[str]:
    _ensure_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT date FROM fii_dii_fao ORDER BY date DESC"
        ).fetchall()
        return [r["date"] for r in rows]


def get_fao_sentiment(fao_data: dict) -> dict:
    pcr = fao_data.get("pcr", 1.0)
    score = fao_data.get("sentiment_score", 50)

    if score >= 65:
        label = "BULLISH"
    elif score >= 55:
        label = "MILD_BULLISH"
    elif score >= 45:
        label = "NEUTRAL"
    elif score >= 35:
        label = "MILD_BEARISH"
    else:
        label = "BEARISH"

    return {
        "pcr": pcr,
        "sentiment_score": score,
        "sentiment_label": label,
        "fii_fut_net": fao_data.get("fii_idx_fut_net", 0),
        "fii_call_net": fao_data.get("fii_idx_call_net", 0),
        "fii_put_net": fao_data.get("fii_idx_put_net", 0),
    }


if __name__ == "__main__":
    today = date.today().strftime("%d-%b-%Y")
    print(f"Fetching F&O data for {today}...")
    result = fetch_and_save_fao(today)
    if result:
        print(f"\nF&O data for {result['date']}:")
        print(f"  FII Index Futures:  Long={result['fii_idx_fut_long']:>10,}  Short={result['fii_idx_fut_short']:>10,}  Net={result['fii_idx_fut_net']:>+10,}")
        print(f"  FII Stock Futures:  Long={result['fii_stk_fut_long']:>10,}  Short={result['fii_stk_fut_short']:>10,}  Net={result['fii_stk_fut_net']:>+10,}")
        print(f"  FII Index Calls:    Long={result['fii_idx_call_long']:>10,}  Short={result['fii_idx_call_short']:>10,}  Net={result['fii_idx_call_net']:>+10,}")
        print(f"  FII Index Puts:     Long={result['fii_idx_put_long']:>10,}  Short={result['fii_idx_put_short']:>10,}  Net={result['fii_idx_put_net']:>+10,}")
        print(f"  DII Index Futures:  Long={result['dii_idx_fut_long']:>10,}  Short={result['dii_idx_fut_short']:>10,}  Net={result['dii_idx_fut_net']:>+10,}")
        print(f"  DII Stock Futures:  Long={result['dii_stk_fut_long']:>10,}  Short={result['dii_stk_fut_short']:>10,}  Net={result['dii_stk_fut_net']:>+10,}")
        sentiment = get_fao_sentiment(result)
        print(f"\n  PCR: {result['pcr']}")
        print(f"  Sentiment: {sentiment['sentiment_label']} ({result['sentiment_score']})")
    else:
        print(f"No F&O data available for {today}.")
        print("\nChecking DB for any existing F&O data...")
        recent = get_recent_fao(5)
        if recent:
            print(f"Found {len(recent)} records in DB:")
            for r in recent:
                print(f"  {r['date']}: PCR={r['pcr']}, Sentiment={r['sentiment_score']}")
        else:
            print("No existing F&O data in DB either.")
