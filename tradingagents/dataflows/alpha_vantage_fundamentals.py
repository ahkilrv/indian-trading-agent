import json
from .alpha_vantage_common import _make_api_request, AlphaVantageRateLimitError


def _av_ticker(ticker: str) -> str:
    """Convert yfinance ticker (.NS/.BO) to bare ticker for AV."""
    return ticker.upper().replace(".NS", "").replace(".BO", "")


def _filter_reports_by_date(result, curr_date: str):
    """Filter annualReports/quarterlyReports to exclude entries after curr_date."""
    if not curr_date or not isinstance(result, dict):
        return result
    for key in ("annualReports", "quarterlyReports"):
        if key in result:
            result[key] = [
                r for r in result[key]
                if r.get("fiscalDateEnding", "") <= curr_date
            ]
    return result


def _is_empty_av_response(raw) -> bool:
    """Check if AV returned empty {} (unsupported ticker)."""
    if isinstance(raw, dict):
        return not raw or not any(k in raw for k in ("Symbol", "symbol"))
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            data = json.loads(raw)
            return not data or not any(k in data for k in ("Symbol", "symbol"))
        except json.JSONDecodeError:
            pass
    return False


def get_fundamentals(ticker: str, curr_date: str = None) -> str:
    """Retrieve fundamentals via Alpha Vantage OVERVIEW.

    AV's OVERVIEW only covers US-listed companies, so Indian stocks (RELIANCE, TCS etc.)
    return empty {}. In that case we raise so route_to_vendor falls through to yfinance.
    """
    raw = _make_api_request("OVERVIEW", {"symbol": _av_ticker(ticker)})
    if _is_empty_av_response(raw):
        raise AlphaVantageRateLimitError(f"AV OVERVIEW not supported for {ticker}")
    return raw


def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """Retrieve balance sheet via Alpha Vantage."""
    result = _make_api_request("BALANCE_SHEET", {"symbol": _av_ticker(ticker)})
    if _is_empty_av_response(result):
        raise AlphaVantageRateLimitError(f"AV BALANCE_SHEET not supported for {ticker}")
    return _filter_reports_by_date(result, curr_date)


def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """Retrieve cash flow via Alpha Vantage."""
    result = _make_api_request("CASH_FLOW", {"symbol": _av_ticker(ticker)})
    if _is_empty_av_response(result):
        raise AlphaVantageRateLimitError(f"AV CASH_FLOW not supported for {ticker}")
    return _filter_reports_by_date(result, curr_date)


def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """Retrieve income statement via Alpha Vantage."""
    result = _make_api_request("INCOME_STATEMENT", {"symbol": _av_ticker(ticker)})
    if _is_empty_av_response(result):
        raise AlphaVantageRateLimitError(f"AV INCOME_STATEMENT not supported for {ticker}")
    return _filter_reports_by_date(result, curr_date)

