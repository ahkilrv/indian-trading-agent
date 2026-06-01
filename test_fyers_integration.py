#!/usr/bin/env python3
"""Standalone integration test for the Fyers data flow.

Usage::

    python test_fyers_integration.py

Prerequisites
-------------
- ``fyers-apiv3`` installed (``pip install fyers-apiv3``)
- ``FYERS_APP_ID``, ``FYERS_SECRET_KEY``, ``FYERS_REDIRECT_URI`` set in ``.env``
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

# Load environment before any other imports that may read os.environ
load_dotenv()


def main() -> None:
    # Append project root so we can import tradingagents
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from tradingagents.dataflows.fyers_data import FyersDataFlow

    print("=" * 60)
    print("Fyers Integration Test")
    print("=" * 60)

    # 1. Initialise
    print("\n[1/4] Initialising FyersDataFlow …")
    flow = FyersDataFlow()

    # 2. Authenticate
    print("[2/4] Authenticating …")
    try:
        flow.authenticate()
    except RuntimeError as exc:
        print(f"\n✗ Authentication failed: {exc}")
        print(
            "  Make sure FYERS_APP_ID and FYERS_SECRET_KEY are set in .env\n"
            "  (Get them from https://myapi.fyers.in/dashboard)"
        )
        sys.exit(1)

    # 3. Fetch 15-min candles for HDFCBANK
    print("[3/4] Fetching 15-min candles for HDFCBANK (last 5 days) …")
    try:
        df = flow.get_historical_data(
            "HDFCBANK",
            "2026-05-22",
            "2026-05-27",
            interval="15",
        )
        if df.empty:
            print("  ⚠ No data returned (market holiday or invalid range?)")
        else:
            print(f"  ✓ Got {len(df)} rows")
            print("\n  Last 5 rows:")
            print(df.tail(5).to_string())
    except Exception as exc:
        print(f"  ✗ Error: {exc}")
        # Continue to quote test anyway

    # 4. Fetch live quote
    print("\n[4/4] Fetching live quote for HDFCBANK …")
    try:
        quote = flow.get_quote("HDFCBANK")
        print(f"  ✓ Quote received:")
        for k, v in quote.items():
            print(f"    {k:>12}: {v}")
    except Exception as exc:
        print(f"  ✗ Error: {exc}")

    print("\n" + "=" * 60)
    print("Test complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()