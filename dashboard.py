"""
Web Dashboard Server for Top 100 Stocks MTF Trading & Comparison System.
Zero-dependency HTTP server delivering interactive UI, real-time technical analysis,
stock comparison tools, and live MTF interest decay & broker liquidation simulations.
"""

import json
import os
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, List, Any

from config import (
    DASHBOARD_PORT,
    DASHBOARD_HOST,
    DHAN_CLIENT_ID,
    DHAN_ACCESS_TOKEN,
    update_access_token
)
from instruments import get_all_stocks, get_stock_by_symbol, get_sector_distribution
from dhan_client import DhanClient
from analyzer import StockAnalyzer
from mtf_risk_engine import MTFRiskEngine

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

# Global cached client & data
_dhan_client = DhanClient()
_cached_stock_data = {}


def get_analyzed_stocks(universe: str = "my_watchlist", force_refresh: bool = False) -> Dict[str, Any]:
    """Fetches, analyzes, and caches stock data for the dashboard."""
    global _dhan_client, _cached_stock_data

    cache_key = universe.lower().replace("-", "_")
    if cache_key in _cached_stock_data and not force_refresh:
        return _cached_stock_data[cache_key]

    stocks = get_all_stocks(universe=cache_key)
    sec_ids = [int(s["security_id"]) for s in stocks]
    ltps = _dhan_client.fetch_ltp_batch(sec_ids)

    analyzed_list = []
    in_buy_zone_count = 0
    near_buy_zone_count = 0
    target_hit_count = 0

    for s in stocks:
        sec_id = s["security_id"]
        current_ltp = ltps.get(sec_id)
        hist = _dhan_client.fetch_historical_daily(sec_id)
        res = StockAnalyzer.analyze_stock(s["symbol"], hist, current_ltp)
        if not res:
            continue

        # Default MTF risk profile
        mtf = MTFRiskEngine.calculate_trade_plan(
            entry_price=res["rec_entry"],
            capital=50000.0,
            margin_pct=s.get("mtf_margin_pct", 0.25),
            stop_loss_price=res["stop_loss"]
        )

        sched_15 = next((x for x in mtf.get("schedule", []) if x["days"] == 15), {})

        res.update({
            "name": s["name"],
            "sector": s["sector"],
            "security_id": sec_id,
            "mtf_margin_pct": s.get("mtf_margin_pct", 0.25),
            "mtf_leverage": mtf.get("leverage", 4.0),
            "mtf_liquidation_price": mtf.get("liquidation_price"),
            "mtf_liquidation_drop_pct": mtf.get("liquidation_drop_pct"),
            "mtf_daily_interest": mtf.get("daily_interest_cost"),
            "mtf_gross_profit": mtf.get("gross_profit"),
            "safety_buffer": mtf.get("safety_cushion_pct"),
            "net_roi_15d": sched_15.get("net_roi_pct", 0.0),
            "net_profit_15d": sched_15.get("net_profit", 0.0),
            "is_sl_safe": mtf.get("is_sl_safe_from_liquidation", True),
            "milestone_1_to_2m": mtf.get("milestone_1_to_2m", {})
        })

        if res["status"] == "BUY_ZONE_ACTIVE":
            in_buy_zone_count += 1
        elif res["status"] == "NEAR_BUY_ZONE":
            near_buy_zone_count += 1
        elif res["status"] == "TARGET_ACHIEVED":
            target_hit_count += 1

        analyzed_list.append(res)

    sectors = get_sector_distribution(universe=cache_key)

    from instruments import WATCHLIST_REGISTRY, get_available_watchlists
    active_title = WATCHLIST_REGISTRY.get(cache_key, {}).get("title", cache_key.upper())

    _cached_stock_data[cache_key] = {
        "stocks": analyzed_list,
        "summary": {
            "total": len(analyzed_list),
            "in_buy_zone": in_buy_zone_count,
            "near_buy_zone": near_buy_zone_count,
            "target_hit": target_hit_count,
            "dhan_client_id": DHAN_CLIENT_ID,
            "universe": cache_key,
            "watchlist": cache_key,
            "watchlist_title": active_title
        },
        "available_watchlists": get_available_watchlists(),
        "sectors": sectors
    }
    return _cached_stock_data[cache_key]


class DashboardRequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_path: Path, status: int = 200):
        if not html_path.exists():
            self.send_error(404, "File Not Found")
            return
        with open(html_path, "rb") as f:
            content = f.read()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        url_path = self.path.split("?")[0]
        query_str = self.path.split("?")[1] if "?" in self.path else ""

        if url_path in ("/", "/index.html"):
            self._send_html(TEMPLATES_DIR / "index.html")
        elif url_path == "/api/stocks":
            from urllib.parse import parse_qs
            params = parse_qs(query_str)
            force = params.get("refresh", ["false"])[0].lower() == "true"

            watchlist = params.get("watchlist", params.get("universe", ["my_watchlist"]))[0]
            if watchlist in ("100", "top_100", "TOP_100"):
                watchlist = "top_100"
            elif watchlist in ("50", "top_50", "TOP_50"):
                watchlist = "top_50"
            elif watchlist in ("next_50", "next50", "NEXT_50"):
                watchlist = "next_50"
            elif watchlist in ("my", "stfi", "my_watchlist", "watchlist"):
                watchlist = "my_watchlist"

            data = get_analyzed_stocks(universe=watchlist, force_refresh=force)
            self._send_json(data)
        elif url_path == "/api/watchlists":
            from instruments import get_available_watchlists
            self._send_json({"watchlists": get_available_watchlists()})
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        global _dhan_client, _cached_stock_data
        url_path = self.path.split("?")[0]
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"

        try:
            payload = json.loads(post_body)
        except Exception:
            self._send_json({"error": "Invalid JSON"}, status=400)
            return

        if url_path == "/api/mtf-calc":
            entry_price = float(payload.get("entry_price", 1000.0))
            capital = float(payload.get("capital", 50000.0))
            margin_pct = float(payload.get("margin_pct", 0.25))
            stop_loss = float(payload.get("stop_loss_price", entry_price * 0.965))
            annual_rate = float(payload.get("annual_interest_rate", 0.10))
            target_pct = float(payload.get("target_pct", 0.10))

            plan = MTFRiskEngine.calculate_trade_plan(
                entry_price=entry_price,
                capital=capital,
                margin_pct=margin_pct,
                target_pct=target_pct,
                stop_loss_price=stop_loss,
                annual_interest_rate=annual_rate
            )
            self._send_json(plan)

        elif url_path == "/api/compare":
            symbols = payload.get("symbols", [])
            capital = float(payload.get("capital", 50000.0))
            if not symbols:
                self._send_json({"error": "No symbols provided"}, status=400)
                return

            compared_list = []
            for sym in symbols[:4]:  # Max 4 stocks for clean comparison
                stock = get_stock_by_symbol(sym)
                if not stock:
                    continue
                sec_id = stock["security_id"]
                ltps = _dhan_client.fetch_ltp_batch([int(sec_id)])
                current_ltp = ltps.get(sec_id)
                hist = _dhan_client.fetch_historical_daily(sec_id)
                analysis = StockAnalyzer.analyze_stock(stock["symbol"], hist, current_ltp)
                mtf = MTFRiskEngine.calculate_trade_plan(
                    entry_price=analysis["rec_entry"],
                    capital=capital,
                    margin_pct=stock.get("mtf_margin_pct", 0.25),
                    stop_loss_price=analysis["stop_loss"]
                )
                sched_15 = next((x for x in mtf.get("schedule", []) if x["days"] == 15), {})
                compared_list.append({
                    "stock": stock,
                    "analysis": analysis,
                    "mtf": mtf,
                    "sched_15": sched_15
                })

            self._send_json({"compared": compared_list})

        elif url_path == "/api/update-token":
            new_token = payload.get("token", "")
            new_client = payload.get("client_id", "")
            if not new_token:
                self._send_json({"success": False, "message": "Access token cannot be empty"}, status=400)
                return

            ok = update_access_token(new_token, new_client)
            if ok:
                _dhan_client = DhanClient()
                _cached_stock_data.clear()  # Invalidate all cache
                self._send_json({"success": True, "message": "Token updated successfully"})
            else:
                self._send_json({"success": False, "message": "Failed to update token"}, status=500)

        else:
            self.send_error(404, "Not Found")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def run_server(port: int = DASHBOARD_PORT, host: str = DASHBOARD_HOST):
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, DashboardRequestHandler)
    print(f"\n🚀 Top 100 Stocks MTF Trading & Comparison Dashboard running at:")
    print(f"   👉 http://{host}:{port}/")
    print(f"   Press Ctrl+C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down dashboard server...")
        httpd.shutdown()


if __name__ == "__main__":
    port = int(os.getenv("PORT", DASHBOARD_PORT))
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0" if os.getenv("PORT") else DASHBOARD_HOST)
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_server(port=port, host=host)
