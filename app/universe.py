"""Nifty 50 ticker universe for the beginner scanner.

Tickers use the Yahoo Finance NSE suffix (.NS).
List is approximate as of 2025; the index is rebalanced periodically and may
need an occasional refresh.
"""

NIFTY_50: list[str] = [
    "RELIANCE.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "BHARTIARTL.NS",
    "ICICIBANK.NS",
    "INFY.NS",
    "SBIN.NS",
    "HINDUNILVR.NS",
    "LT.NS",
    "ITC.NS",
    "LICI.NS",
    "KOTAKBANK.NS",
    "AXISBANK.NS",
    "BAJFINANCE.NS",
    "MARUTI.NS",
    "ONGC.NS",
    "ADANIENT.NS",
    "NTPC.NS",
    "M&M.NS",
    "HCLTECH.NS",
    "ASIANPAINT.NS",
    "ULTRACEMCO.NS",
    "SUNPHARMA.NS",
    "TITAN.NS",
    "WIPRO.NS",
    "BAJAJFINSV.NS",
    "ADANIPORTS.NS",
    "COALINDIA.NS",
    "NESTLEIND.NS",
    "POWERGRID.NS",
    "JSWSTEEL.NS",
    "TATASTEEL.NS",
    "TATAMOTORS.NS",
    "INDUSINDBK.NS",
    "GRASIM.NS",
    "HINDALCO.NS",
    "BPCL.NS",
    "EICHERMOT.NS",
    "BAJAJ-AUTO.NS",
    "SBILIFE.NS",
    "BRITANNIA.NS",
    "HDFCLIFE.NS",
    "CIPLA.NS",
    "DRREDDY.NS",
    "DIVISLAB.NS",
    "APOLLOHOSP.NS",
    "HEROMOTOCO.NS",
    "TECHM.NS",
    "TATACONSUM.NS",
    "SHRIRAMFIN.NS",
]


def display_name(ticker: str) -> str:
    """Strip the .NS suffix for display."""
    return ticker.replace(".NS", "")
