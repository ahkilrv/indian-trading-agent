"""Fundamentals data from Screener.in — reliable Indian stock fundamentals."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_SEARCH_URL = "https://www.screener.in/api/company/search/?q={query}&v=3"
_COMPANY_URL = "https://www.screener.in/company/{slug}/consolidated/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}
_REQUEST_DELAY = 2.0  # seconds between requests to screener.in
_last_request = 0.0


def _rate_limit():
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < _REQUEST_DELAY:
        time.sleep(_REQUEST_DELAY - elapsed)
    _last_request = time.time()


def _fetch(url: str) -> str:
    _rate_limit()
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        logger.warning("Screener HTTP %s for %s", e.code, url)
        raise
    except urllib.error.URLError as e:
        logger.warning("Screener URL error for %s: %s", url, e.reason)
        raise


def _search(ticker: str) -> tuple[int, str] | None:
    """Search screener.in and return (company_id, url_slug) or None."""
    bare = ticker.upper().replace(".NS", "").replace(".BO", "")
    url = _SEARCH_URL.format(query=urllib.parse.quote(bare))
    raw = _fetch(url)
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        logger.warning("Screener search returned empty for %s", ticker)
        return None
    # Prefer entry whose URL slug matches the bare ticker
    for entry in data:
        url_slug = entry["url"].strip("/").split("/")[1] if entry["url"].strip("/").startswith("company/") else ""
        if url_slug.upper() == bare:
            slug = url_slug
            return entry["id"], slug
    # Fallback: first search result (Screener ranks by relevance)
    first = data[0]
    slug = first["url"].strip("/").removesuffix("/consolidated").removeprefix("company/")
    return first["id"], slug


def _extract_name(soup: BeautifulSoup) -> str | None:
    """Extract company name from page title."""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)
        # Format: "Reliance Industries Ltd share price | ..."
        name = title.split(" share price")[0].strip()
        return name
    return None


def _extract_sector(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Extract sector and industry from peer breadcrumb."""
    peers = soup.find("section", id="peers")
    if not peers:
        return None, None
    breadcrumb = peers.find("p", class_="sub")
    if not breadcrumb:
        return None, None
    links = breadcrumb.find_all("a")
    sector = None
    industry = None
    for link in links:
        href = link.get("href", "")
        title = link.get("title", "")
        text = link.get_text(strip=True)
        if "/market/IN03/" in href and len(href.strip("/").split("/")) == 3:
            sector = text
        elif "/market/IN03/" in href and len(href.strip("/").split("/")) >= 6:
            industry = text
    return sector, industry


def _extract_ratios(soup: BeautifulSoup) -> dict[str, str]:
    """Extract key ratios from the #top-ratios list."""
    ratios = {}
    ul = soup.find("ul", id="top-ratios")
    if not ul:
        return ratios
    for li in ul.find_all("li"):
        name_el = li.find("span", class_="name")
        val_el = li.find("span", class_="value")
        if not name_el or not val_el:
            continue
        name = name_el.get_text(strip=True)
        val = val_el.get_text(strip=True)
        # Normalise value
        val = val.replace("₹", "").replace("Cr.", "").replace(",", "").strip()
        ratios[name] = val
    return ratios


def _extract_quarterly(soup: BeautifulSoup) -> dict[str, list]:
    """Extract the most recent quarter's P&L data."""
    section = soup.find("section", id="quarters")
    if not section:
        return {}
    table = section.find("table", class_="data-table")
    if not table:
        return {}
    rows = table.find_all("tr")
    data = {}
    for row in rows:
        tds = row.find_all("td")
        if not tds:
            continue
        label_el = tds[0]
        label = label_el.get_text(strip=True).removesuffix("+").strip()
        values = []
        for td in tds[1:]:
            raw = td.get_text(strip=True)
            raw = raw.replace(",", "")
            try:
                values.append(float(raw))
            except ValueError:
                values.append(0.0 if raw == "-" else raw)
        if values:
            data[label] = values
    return data


def _safe_float(val) -> Optional[float]:
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _format_output(ticker: str, name: str | None, sector: str | None, industry: str | None, ratios: dict, quarterly: dict) -> str:
    """Format scraped data into a yfinance-compatible text block."""
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# Company Fundamentals for {ticker}",
        f"# Data retrieved on: {now_str}",
        "",
    ]

    if name:
        lines.append(f"Name: {name}")
    if sector:
        lines.append(f"Sector: {sector}")
    if industry:
        lines.append(f"Industry: {industry}")

    field_map = {
        "Market Cap": ("Market Cap", lambda v: v),
        "Stock P/E": ("PE Ratio (TTM)", None),
        "Book Value": ("Book Value", None),
        "Dividend Yield": ("Dividend Yield", None),
        "ROCE": ("ROCE", lambda v: f"{v}%" if "%" not in str(v) and v else v),
        "ROE": ("ROE", lambda v: f"{v}%" if "%" not in str(v) and v else v),
        "Face Value": ("Face Value", None),
        "High / Low": ("High / Low", None),
    }

    for screener_key, (label, fmt) in field_map.items():
        val = ratios.get(screener_key)
        if val:
            if fmt:
                val = fmt(val)
            lines.append(f"{label}: {val}")

    # Add quarterly snapshot
    if quarterly:
        lines.append("")
        lines.append("# Quarterly Snapshot (Most Recent Quarter)")
        for key in ("Sales", "Expenses", "Operating Profit", "OPM %", "Net Profit", "EPS in Rs"):
            vals = quarterly.get(key)
            if vals and len(vals) > 0:
                latest = vals[-1]
                if isinstance(latest, (int, float)):
                    lines.append(f"{key}: {latest:,.2f}")
                else:
                    lines.append(f"{key}: {latest}")

    return "\n".join(lines)


def get_screener_fundamentals(ticker: str, curr_date: str = None) -> str:
    """Retrieve Indian stock fundamentals from Screener.in.

    Returns a formatted text string compatible with the existing
    yfinance fundamentals format for seamless integration.

    Args:
        ticker: NSE/BSE ticker (e.g. RELIANCE, RELIANCE.NS)
        curr_date: Current date yyyy-mm-dd (optional, used for look-ahead bias)

    Returns:
        Formatted fundamentals text or error message.
    """
    import urllib.parse

    ticker_clean = ticker.upper().replace(".NS", "").replace(".BO", "")

    try:
        result = _search(ticker)
        if not result:
            return f"No fundamentals data found for symbol '{ticker}'"
        company_id, slug = result
    except Exception as e:
        logger.warning("Screener search failed for %s: %s", ticker, e)
        return f"Fundamentals temporarily unavailable for '{ticker}'"

    try:
        url = _COMPANY_URL.format(slug=slug)
        html = _fetch(url)
    except Exception as e:
        logger.warning("Screener fetch failed for %s: %s", ticker, e)
        return f"Fundamentals temporarily unavailable for '{ticker}'"

    try:
        soup = BeautifulSoup(html, "lxml")
        name = _extract_name(soup)
        sector, industry = _extract_sector(soup)
        ratios = _extract_ratios(soup)
        quarterly = _extract_quarterly(soup)
        return _format_output(ticker, name, sector, industry, ratios, quarterly)
    except Exception as e:
        logger.warning("Screener parse failed for %s: %s", ticker, e)
        return f"No fundamentals data found for symbol '{ticker}'"
