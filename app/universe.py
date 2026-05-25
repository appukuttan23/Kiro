"""Stock-universe lists for the scanner.

All tickers use the Yahoo Finance NSE suffix (.NS).

Available universes:
- NIFTY_50         : Top 50 by free-float market cap
- NIFTY_NEXT_50    : Next 50 (mid-large cap)
- NIFTY_100        : NIFTY_50 + NIFTY_NEXT_50
- FNO_EXTRA        : Curated liquid F&O names *outside* Nifty 100
- FNO_LIQUID       : NIFTY_100 + FNO_EXTRA (best for breakout / momentum hunters)

Index lists are approximate as of mid-2026; rebalance every quarter.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Nifty 50 (~50 names)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Nifty Next 50 (~50 names) — large/mid-cap, completes Nifty 100
# ---------------------------------------------------------------------------
NIFTY_NEXT_50: list[str] = [
    "ABB.NS",
    "ADANIGREEN.NS",
    "ADANIPOWER.NS",
    "AMBUJACEM.NS",
    "BAJAJHLDNG.NS",
    "BANKBARODA.NS",
    "BEL.NS",
    "BERGEPAINT.NS",
    "BOSCHLTD.NS",
    "CANBK.NS",
    "CGPOWER.NS",
    "CHOLAFIN.NS",
    "COLPAL.NS",
    "DABUR.NS",
    "DLF.NS",
    "DMART.NS",
    "GAIL.NS",
    "GODREJCP.NS",
    "HAL.NS",
    "HAVELLS.NS",
    "HINDPETRO.NS",
    "ICICIGI.NS",
    "ICICIPRULI.NS",
    "INDIGO.NS",
    "INDUSTOWER.NS",
    "IOC.NS",
    "IRCTC.NS",
    "JINDALSTEL.NS",
    "JIOFIN.NS",
    "LODHA.NS",
    "LTIM.NS",
    "MARICO.NS",
    "MOTHERSON.NS",
    "NAUKRI.NS",
    "PFC.NS",
    "PIDILITIND.NS",
    "PIIND.NS",
    "PNB.NS",
    "POLYCAB.NS",
    "RECLTD.NS",
    "SBICARD.NS",
    "SHREECEM.NS",
    "SIEMENS.NS",
    "SRF.NS",
    "TATAPOWER.NS",
    "TORNTPHARM.NS",
    "TRENT.NS",
    "TVSMOTOR.NS",
    "VEDL.NS",
    "ZOMATO.NS",
]


# ---------------------------------------------------------------------------
# Liquid F&O names *outside* Nifty 100 — curated. These are stocks that show
# up regularly in NSE's "Most Active F&O Contracts" list.
# ---------------------------------------------------------------------------
FNO_EXTRA: list[str] = [
    "ABCAPITAL.NS",
    "ABFRL.NS",
    "ACC.NS",
    "ASHOKLEY.NS",
    "AUBANK.NS",
    "BANDHANBNK.NS",
    "BHARATFORG.NS",
    "BIOCON.NS",
    "BSOFT.NS",
    "CONCOR.NS",
    "COROMANDEL.NS",
    "CUMMINSIND.NS",
    "DEEPAKNTR.NS",
    "ESCORTS.NS",
    "EXIDEIND.NS",
    "FEDERALBNK.NS",
    "GLENMARK.NS",
    "GMRINFRA.NS",
    "GRANULES.NS",
    "HINDCOPPER.NS",
    "IDEA.NS",
    "IDFCFIRSTB.NS",
    "INDIANB.NS",
    "INDUSINDBK.NS",
    "IPCALAB.NS",
    "JKCEMENT.NS",
    "JUBLFOOD.NS",
    "LALPATHLAB.NS",
    "LICHSGFIN.NS",
    "LUPIN.NS",
    "M&MFIN.NS",
    "MANAPPURAM.NS",
    "MFSL.NS",
    "MGL.NS",
    "MUTHOOTFIN.NS",
    "NATIONALUM.NS",
    "NMDC.NS",
    "OBEROIRLTY.NS",
    "PERSISTENT.NS",
    "PETRONET.NS",
    "PVRINOX.NS",
    "RAMCOCEM.NS",
    "SAIL.NS",
    "SUNTV.NS",
    "SYNGENE.NS",
    "TATACOMM.NS",
    "TATAELXSI.NS",
    "UPL.NS",
    "VOLTAS.NS",
    "ZYDUSLIFE.NS",
]


# ---------------------------------------------------------------------------
# Composite universes
# ---------------------------------------------------------------------------
NIFTY_100: list[str] = NIFTY_50 + NIFTY_NEXT_50

# Dedupe while preserving order (INDUSINDBK appears in both NIFTY_50 and FNO_EXTRA)
def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


FNO_LIQUID: list[str] = _dedupe(NIFTY_100 + FNO_EXTRA)


UNIVERSES: dict[str, list[str]] = {
    "NIFTY_50": NIFTY_50,
    "NIFTY_NEXT_50": NIFTY_NEXT_50,
    "NIFTY_100": NIFTY_100,
    "FNO_LIQUID": FNO_LIQUID,
}


def get_universe(name: str = "NIFTY_50") -> list[str]:
    """Return the ticker list for a named universe.

    Falls back to NIFTY_50 if the name is unknown.
    """
    return UNIVERSES.get(name.upper(), NIFTY_50)


def list_universes() -> list[dict]:
    """Metadata for the UI dropdown."""
    return [
        {"name": name, "size": len(tickers)}
        for name, tickers in UNIVERSES.items()
    ]


def display_name(ticker: str) -> str:
    """Strip the .NS suffix for display."""
    return ticker.replace(".NS", "")
