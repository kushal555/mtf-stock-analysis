"""
Instruments module for Top 100 Stocks, Nifty 50, and Custom User Watchlists.
Supports multi-watchlist switching ('my_watchlist' / 'to add stfi', 'top_100', 'top_50', 'next_50').
"""

from typing import Dict, List, Optional
import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
JSON_PATH = BASE_DIR / "top_100_data.json"

# Load the verified 100 stocks dataset
if JSON_PATH.exists():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        TOP_100_STOCKS: List[Dict] = json.load(f)
else:
    TOP_100_STOCKS: List[Dict] = []

TOP_50_STOCKS: List[Dict] = TOP_100_STOCKS[:50]
NIFTY_NEXT_50_STOCKS: List[Dict] = TOP_100_STOCKS[50:]

# User's Custom Watchlist (22 stocks from user screenshots)
USER_WATCHLIST_STOCKS: List[Dict] = [
    {"symbol": "NETWEB", "name": "Netweb Technologies India Ltd", "security_id": "17433", "sector": "IT & High-End Computing", "mtf_margin_pct": 0.25, "base_price": 5027.00},
    {"symbol": "NEULANDLAB", "name": "Neuland Laboratories Ltd", "security_id": "2406", "sector": "Pharma & API", "mtf_margin_pct": 0.25, "base_price": 23535.00},
    {"symbol": "CGPOWER", "name": "CG Power and Industrial Solutions", "security_id": "760", "sector": "Capital Goods & Power", "mtf_margin_pct": 0.25, "base_price": 909.00},
    {"symbol": "AADHARHFC", "name": "Aadhar Housing Finance Ltd", "security_id": "23729", "sector": "Housing Finance", "mtf_margin_pct": 0.25, "base_price": 456.80},
    {"symbol": "JSWCEMENT", "name": "JSW Cement Ltd", "security_id": "758460", "sector": "Cement & Building Materials", "mtf_margin_pct": 0.25, "base_price": 118.87},
    {"symbol": "PSPPROJECT", "name": "PSP Projects Ltd", "security_id": "20877", "sector": "Construction & Infra", "mtf_margin_pct": 0.25, "base_price": 846.40},
    {"symbol": "DATAPATTNS", "name": "Data Patterns (India) Ltd", "security_id": "7358", "sector": "Defence & Aerospace Electronics", "mtf_margin_pct": 0.25, "base_price": 4829.20},
    {"symbol": "DHANUKA", "name": "Dhanuka Agritech Ltd", "security_id": "24409", "sector": "Agro Chemicals", "mtf_margin_pct": 0.22, "base_price": 980.00},
    {"symbol": "SJS", "name": "S.J.S. Enterprises Ltd", "security_id": "6643", "sector": "Auto Ancillary & Aesthetics", "mtf_margin_pct": 0.25, "base_price": 2354.00},
    {"symbol": "AARTIPHARM", "name": "Aarti Pharmalabs Ltd", "security_id": "13868", "sector": "Pharma & API", "mtf_margin_pct": 0.25, "base_price": 826.95},
    {"symbol": "BALMLAWRIE", "name": "Balmer Lawrie & Company Ltd", "security_id": "338", "sector": "Logistics & Industrial", "mtf_margin_pct": 0.25, "base_price": 168.72},
    {"symbol": "EIHOTEL", "name": "EIH Limited (Oberoi Hotels)", "security_id": "919", "sector": "Hospitality & Hotels", "mtf_margin_pct": 0.22, "base_price": 286.45},
    {"symbol": "ENGINERSIN", "name": "Engineers India Ltd", "security_id": "4907", "sector": "Engineering Consultancy", "mtf_margin_pct": 0.25, "base_price": 268.95},
    {"symbol": "FORCEMOT", "name": "Force Motors Ltd", "security_id": "11573", "sector": "Automobile & Vans", "mtf_margin_pct": 0.25, "base_price": 17705.00},
    {"symbol": "JIOFIN", "name": "Jio Financial Services Ltd", "security_id": "18143", "sector": "Financial Services", "mtf_margin_pct": 0.22, "base_price": 229.90},
    {"symbol": "VINDHYATEL", "name": "Vindhya Telelinks Ltd", "security_id": "3694", "sector": "Telecom Cables & EPC", "mtf_margin_pct": 0.25, "base_price": 2813.50},
    {"symbol": "LANDMARK", "name": "Landmark Cars Ltd", "security_id": "13276", "sector": "Auto Dealerships", "mtf_margin_pct": 0.25, "base_price": 487.95},
    {"symbol": "EPIGRAL", "name": "Epigral Ltd", "security_id": "5382", "sector": "Specialty Chemicals", "mtf_margin_pct": 0.25, "base_price": 1131.10},
    {"symbol": "TVSHLTD", "name": "TVS Holdings Ltd", "security_id": "29008", "sector": "Auto Ancillary & Holding", "mtf_margin_pct": 0.25, "base_price": 13024.00},
    {"symbol": "SAFARI", "name": "Safari Industries (India) Ltd", "security_id": "13035", "sector": "Consumer Luggage", "mtf_margin_pct": 0.25, "base_price": 1544.70},
    {"symbol": "ABSLAMC", "name": "Aditya Birla Sun Life AMC Ltd", "security_id": "6018", "sector": "Asset Management", "mtf_margin_pct": 0.22, "base_price": 1109.90},
    {"symbol": "CELLO", "name": "Cello World Ltd", "security_id": "19795", "sector": "Consumer Products", "mtf_margin_pct": 0.25, "base_price": 332.80}
]

# Master Registry of Watchlists
WATCHLIST_REGISTRY: Dict[str, Dict] = {
    "my_watchlist": {
        "id": "my_watchlist",
        "title": "MTF-Watchlist",
        "stocks": USER_WATCHLIST_STOCKS
    },
    "mtf_watchlist": {
        "id": "mtf_watchlist",
        "title": "MTF-Watchlist",
        "stocks": USER_WATCHLIST_STOCKS
    },
    "top_100": {
        "id": "top_100",
        "title": "Top 100 Companies",
        "stocks": TOP_100_STOCKS
    },
    "top_50": {
        "id": "top_50",
        "title": "NIFTY 50",
        "stocks": TOP_50_STOCKS
    },
    "next_50": {
        "id": "next_50",
        "title": "NIFTY Next 50",
        "stocks": NIFTY_NEXT_50_STOCKS
    }
}

# Unified lookup across all stock universes
_ALL_UNIQUE_STOCKS: List[Dict] = []
_SEEN_SYMBOLS = set()
for stock_list in [USER_WATCHLIST_STOCKS, TOP_100_STOCKS]:
    for s in stock_list:
        sym = s["symbol"].upper()
        if sym not in _SEEN_SYMBOLS:
            _ALL_UNIQUE_STOCKS.append(s)
            _SEEN_SYMBOLS.add(sym)

_BY_SYMBOL: Dict[str, Dict] = {s["symbol"].upper(): s for s in _ALL_UNIQUE_STOCKS}
_BY_SECURITY_ID: Dict[str, Dict] = {str(s["security_id"]): s for s in _ALL_UNIQUE_STOCKS}

_SYMBOL_ALIASES = {
    "ZOMATO": "ETERNAL",
    "TATAMOTORS": "TMPV",
    "TATA MOTORS": "TMPV",
    "TML": "TMPV",
    "TMCV": "TMPV"
}


def get_available_watchlists() -> List[Dict[str, Any]]:
    """Returns metadata for all available selectable watchlists."""
    seen_titles = set()
    result = []
    for k, v in WATCHLIST_REGISTRY.items():
        if v["title"] not in seen_titles:
            seen_titles.add(v["title"])
            result.append({
                "id": k,
                "title": v["title"],
                "count": len(v["stocks"])
            })
    return result


def get_all_stocks(universe: str = "my_watchlist") -> List[Dict]:
    """
    Returns the list of stocks for a given universe or watchlist.
    Accepted values: 'my_watchlist' (default), 'top_100', 'top_50', 'next_50', 'TOP_100', 'TOP_50'.
    """
    key = universe.lower().replace("-", "_")
    if key in WATCHLIST_REGISTRY:
        return list(WATCHLIST_REGISTRY[key]["stocks"])
    if key in ("top_100", "100"):
        return list(TOP_100_STOCKS)
    if key in ("top_50", "50"):
        return list(TOP_50_STOCKS)
    return list(USER_WATCHLIST_STOCKS)


def get_stock_by_symbol(symbol: str) -> Optional[Dict]:
    """Lookup stock by symbol across all known watchlists, resolving corporate aliases."""
    s_upper = symbol.strip().upper()
    resolved = _SYMBOL_ALIASES.get(s_upper, s_upper)
    return _BY_SYMBOL.get(resolved) or _BY_SYMBOL.get(s_upper)


def get_stock_by_security_id(security_id: str) -> Optional[Dict]:
    """Lookup stock by Dhan security ID across all known watchlists."""
    return _BY_SECURITY_ID.get(str(security_id).strip())


def get_security_id_list(universe: str = "my_watchlist") -> List[int]:
    """Returns integer security IDs for marketfeed API."""
    stocks = get_all_stocks(universe)
    return [int(s["security_id"]) for s in stocks]


def get_sector_distribution(universe: str = "my_watchlist") -> Dict[str, int]:
    """Returns count of stocks per sector for the selected watchlist."""
    stocks = get_all_stocks(universe)
    dist = {}
    for s in stocks:
        sec = s.get("sector", "Other")
        dist[sec] = dist.get(sec, 0) + 1
    return dict(sorted(dist.items(), key=lambda x: x[1], reverse=True))
