"""
Command-line Scanner & MTF Analyzer for Top 100 Stocks.
Usage:
    python cli.py --scan                        # Scan Top 100 stocks
    python cli.py --buy-zone                    # Show stocks currently inside Buy Zone
    python cli.py --compare RELIANCE TCS HAL    # Side-by-side comparison of stocks
    python cli.py --stock RELIANCE              # Detailed MTF trade plan for a stock
    python cli.py --sector Banking              # Filter by sector
    python cli.py --sort rr                     # Sort by Risk/Reward ratio
    python cli.py --universe 50                 # Switch to Top 50 universe
"""

import sys
import argparse
from typing import List, Dict

from instruments import get_all_stocks, get_stock_by_symbol, get_sector_distribution
from dhan_client import DhanClient
from analyzer import StockAnalyzer
from mtf_risk_engine import MTFRiskEngine


# ANSI Color Codes
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_banner(count: int = 100):
    print(f"{BOLD}{CYAN}========================================================================================{RESET}")
    print(f"{BOLD}{CYAN}      TOP {count} STOCKS MTF SCANNER & COMPARISON (BUY/SELL ZONES & RISK MANAGEMENT)       {RESET}")
    print(f"{BOLD}{CYAN}========================================================================================{RESET}")


def scan_stocks(only_buy_zone: bool = False, capital: float = 50000.0, universe: str = "TOP_100", sector_filter: str = None, sort_by: str = None):
    client = DhanClient()
    stocks = get_all_stocks(universe)
    
    if sector_filter:
        stocks = [s for s in stocks if sector_filter.lower() in s.get("sector", "").lower()]

    print(f"\n{BOLD}Fetching market data for {len(stocks)} stocks ({universe})...{RESET}")
    sec_ids = [int(s["security_id"]) for s in stocks]
    ltps = client.fetch_ltp_batch(sec_ids)
    
    results = []
    print(f"Analyzing technical zones and MTF parameters...")
    for s in stocks:
        sec_id = s["security_id"]
        hist = client.fetch_historical_daily(sec_id)
        current_ltp = ltps.get(sec_id)
        analysis = StockAnalyzer.analyze_stock(s["symbol"], hist, current_ltp)
        if not analysis:
            continue
        
        # Calculate MTF plan
        mtf = MTFRiskEngine.calculate_trade_plan(
            entry_price=analysis["rec_entry"],
            capital=capital,
            margin_pct=s.get("mtf_margin_pct", 0.25),
            stop_loss_price=analysis["stop_loss"]
        )
        
        # 15 days net ROI
        sched_15 = next((x for x in mtf.get("schedule", []) if x["days"] == 15), {})

        results.append({
            "symbol": s["symbol"],
            "name": s["name"],
            "sector": s["sector"],
            "ltp": analysis["ltp"],
            "buy_zone": f"₹{analysis['buy_zone_min']} - ₹{analysis['buy_zone_max']}",
            "rec_entry": analysis["rec_entry"],
            "target_10": analysis["target_10_pct"],
            "stop_loss": analysis["stop_loss"],
            "status": analysis["status"],
            "status_desc": analysis["status_desc"],
            "dist_pct": analysis["dist_to_buy_pct"],
            "rr_ratio": analysis["risk_reward_ratio"],
            "liq_price": mtf["liquidation_price"],
            "safety_buffer": mtf["safety_cushion_pct"],
            "daily_interest": mtf["daily_interest_cost"],
            "gross_profit": mtf["gross_profit"],
            "net_roi_15d": sched_15.get("net_roi_pct", 0.0),
            "leverage": mtf["leverage"]
        })

    if only_buy_zone:
        results = [r for r in results if r["status"] in ("BUY_ZONE_ACTIVE", "NEAR_BUY_ZONE")]

    # Sorting
    if sort_by == "rr":
        results.sort(key=lambda x: x["rr_ratio"], reverse=True)
    elif sort_by == "dist":
        results.sort(key=lambda x: x["dist_pct"])
    elif sort_by == "roi":
        results.sort(key=lambda x: x["net_roi_15d"], reverse=True)
    elif sort_by == "buffer":
        results.sort(key=lambda x: x["safety_buffer"], reverse=True)

    print(f"\n{BOLD}{'SYMBOL':<12} {'SECTOR':<18} {'LTP (₹)':<10} {'BUY ZONE (₹)':<22} {'TARGET (+10%)':<14} {'STOP LOSS':<12} {'STATUS':<20} {'R:R':<6} {'15d NET ROI':<10}{RESET}")
    print("-" * 125)

    for r in results:
        status_str = r["status"]
        if status_str == "BUY_ZONE_ACTIVE":
            colored_status = f"{GREEN}● IN BUY ZONE{RESET}"
        elif status_str == "NEAR_BUY_ZONE":
            colored_status = f"{YELLOW}▲ NEAR (+{r['dist_pct']}%) {RESET}"
        elif status_str == "TARGET_ACHIEVED":
            colored_status = f"{CYAN}★ 10% TARGET{RESET}"
        elif status_str == "STOP_LOSS_HIT":
            colored_status = f"{RED}✖ STOP LOSS{RESET}"
        else:
            colored_status = f"○ WAIT PULLBACK"

        print(f"{BOLD}{r['symbol']:<12}{RESET} {r['sector'][:16]:<18} ₹{r['ltp']:<9.2f} {r['buy_zone']:<22} ₹{r['target_10']:<13.2f} ₹{r['stop_loss']:<11.2f} {colored_status:<30} {r['rr_ratio']:<6.1f} +{r['net_roi_15d']:.1f}%")

    print("-" * 125)
    print(f"Total stocks displayed: {len(results)} | Universe: {universe}")


def compare_stocks(symbols: List[str], capital: float = 50000.0):
    """Prints a structured side-by-side comparison of 2-4 stocks."""
    client = DhanClient()
    compared_data = []

    for sym in symbols:
        stock = get_stock_by_symbol(sym)
        if not stock:
            print(f"{RED}Warning: '{sym}' not recognized in Top 100 universe.{RESET}")
            continue

        sec_id = stock["security_id"]
        ltps = client.fetch_ltp_batch([int(sec_id)])
        current_ltp = ltps.get(sec_id)
        hist = client.fetch_historical_daily(sec_id)
        analysis = StockAnalyzer.analyze_stock(stock["symbol"], hist, current_ltp)
        mtf = MTFRiskEngine.calculate_trade_plan(
            entry_price=analysis["rec_entry"],
            capital=capital,
            margin_pct=stock.get("mtf_margin_pct", 0.25),
            stop_loss_price=analysis["stop_loss"]
        )
        sched_15 = next((x for x in mtf.get("schedule", []) if x["days"] == 15), {})

        compared_data.append({
            "stock": stock,
            "analysis": analysis,
            "mtf": mtf,
            "sched_15": sched_15
        })

    if not compared_data:
        print(f"{RED}No valid stocks to compare.{RESET}")
        return

    print_banner()
    print(f"\n{BOLD}SIDE-BY-SIDE MTF COMPARISON (Invested Margin: ₹{capital:,.2f}){RESET}\n")

    headers = [f"{c['stock']['symbol']} ({c['stock']['sector'][:12]})" for c in compared_data]
    col_width = 24
    header_line = f"{'METRIC':<28} " + " ".join([f"{h:<{col_width}}" for h in headers])
    print(BOLD + header_line + RESET)
    print("-" * len(header_line))

    metrics = [
        ("Current Price (LTP)", lambda c: f"₹{c['analysis']['ltp']:,.2f}"),
        ("Action Status", lambda c: f"{c['analysis']['status']}"),
        ("Distance to Buy Zone", lambda c: f"+{c['analysis']['dist_to_buy_pct']}%" if c['analysis']['dist_to_buy_pct'] > 0 else "In Zone!"),
        ("Suggested Buy Zone", lambda c: f"₹{c['analysis']['buy_zone_min']} - {c['analysis']['buy_zone_max']}"),
        ("10% Target (Sell Zone)", lambda c: f"₹{c['analysis']['target_10_pct']:,.2f}"),
        ("Safe Stop-Loss", lambda c: f"₹{c['analysis']['stop_loss']:,.2f}"),
        ("Risk-to-Reward Ratio", lambda c: f"1 : {c['analysis']['risk_reward_ratio']}"),
        ("MTF Leverage", lambda c: f"{c['mtf']['leverage']}x ({int(c['stock']['mtf_margin_pct']*100)}% Margin)"),
        ("Total Position Size", lambda c: f"₹{c['mtf']['position_value']:,.2f} ({c['mtf']['quantity']} shares)"),
        ("Borrowed Capital", lambda c: f"₹{c['mtf']['borrowed_amount']:,.2f}"),
        ("Daily Interest Cost", lambda c: f"₹{c['mtf']['daily_interest_cost']:,.2f} / day"),
        ("Gross 10% Profit", lambda c: f"₹{c['mtf']['gross_profit']:,.2f}"),
        ("15-Day Net Profit", lambda c: f"₹{c['sched_15'].get('net_profit', 0):,.2f}"),
        ("15-Day Net ROI (%)", lambda c: f"+{c['sched_15'].get('net_roi_pct', 0):.1f}%"),
        ("Broker Liquidation Price", lambda c: f"₹{c['mtf']['liquidation_price']:,.2f} (-{c['mtf']['liquidation_drop_pct']}%)"),
        ("Liquidation Safety Cushion", lambda c: f"+{c['mtf']['safety_cushion_pct']}% Above RMS")
    ]

    for label, extractor in metrics:
        values = [f"{extractor(c):<{col_width}}" for c in compared_data]
        print(f"{label:<28} " + " ".join(values))

    print("-" * len(header_line))

    # Determine Best Pick
    best_pick = max(compared_data, key=lambda c: (
        1 if c['analysis']['status'] == 'BUY_ZONE_ACTIVE' else 0,
        c['analysis']['risk_reward_ratio'],
        c['sched_15'].get('net_roi_pct', 0)
    ))

    print(f"\n{GREEN}{BOLD}★ TOP MTF RECOMMENDATION: {best_pick['stock']['symbol']} ({best_pick['stock']['name']}){RESET}")
    print(f"  Reason: Favorable {best_pick['analysis']['status']} status with 1:{best_pick['analysis']['risk_reward_ratio']} R:R and +{best_pick['sched_15'].get('net_roi_pct', 0):.1f}% 15-day Net ROI.\n")


def show_stock_detail(symbol: str, capital: float = 50000.0):
    stock = get_stock_by_symbol(symbol)
    if not stock:
        print(f"{RED}Error: Symbol '{symbol}' not found in Top 100 universe.{RESET}")
        return

    client = DhanClient()
    sec_id = stock["security_id"]
    ltps = client.fetch_ltp_batch([int(sec_id)])
    current_ltp = ltps.get(sec_id)
    hist = client.fetch_historical_daily(sec_id)
    analysis = StockAnalyzer.analyze_stock(stock["symbol"], hist, current_ltp)
    mtf = MTFRiskEngine.calculate_trade_plan(
        entry_price=analysis["rec_entry"],
        capital=capital,
        margin_pct=stock.get("mtf_margin_pct", 0.25),
        stop_loss_price=analysis["stop_loss"]
    )

    print_banner()
    print(f"\n{BOLD}STOCK ANALYSIS:{RESET} {stock['name']} ({BOLD}{stock['symbol']}{RESET}) | Sector: {stock['sector']}")
    print(f"Current LTP: {BOLD}₹{analysis['ltp']}{RESET}")
    print(f"Status: {BOLD}{analysis['status']}{RESET} - {analysis['status_desc']}")
    print(f"\n{BOLD}--- TRADE LEVELS ---{RESET}")
    print(f"Suggested Entry / Buy Zone: {GREEN}₹{analysis['buy_zone_min']} - ₹{analysis['buy_zone_max']}{RESET} (Ref Entry: ₹{analysis['rec_entry']})")
    print(f"Sell Zone (+10% Profit Target): {CYAN}₹{analysis['sell_zone_min']} - ₹{analysis['sell_zone_max']}{RESET} (Target: ₹{analysis['target_10_pct']})")
    print(f"Recommended Stop Loss:      {RED}₹{analysis['stop_loss']}{RESET} (Max risk: {analysis['risk_per_share']} per share)")
    print(f"Risk-to-Reward Ratio:       {BOLD}1 : {analysis['risk_reward_ratio']}{RESET}")

    print(f"\n{BOLD}--- MTF POSITION PLAN ---{RESET}")
    print(f"Your Capital Deployed (Margin): ₹{mtf['invested_margin']:,.2f}")
    print(f"MTF Leverage:                  {mtf['leverage']}x (Margin requirement: {int(stock['mtf_margin_pct']*100)}%)")
    print(f"Total Trade Value:             ₹{mtf['position_value']:,.2f} ({mtf['quantity']} shares)")
    print(f"Broker Borrowed Amount:        ₹{mtf['borrowed_amount']:,.2f}")
    print(f"Daily Interest Accrual:        ₹{mtf['daily_interest_cost']:,.2f} / day (MTF ~10% p.a.)")
    print(f"Estimated Statutory Charges:   ₹{mtf['statutory_charges']:,.2f} (STT, Stamp Duty, GST)")
    print(f"Gross 10% Profit at Target:    {GREEN}₹{mtf['gross_profit']:,.2f} (+{mtf['gross_roi_pct']}% on Margin!){RESET}")

    ms = mtf.get("milestone_1_to_2m", {})
    if ms:
        print(f"\n{BOLD}--- 1–2 MONTH MTF INTEREST ADVANTAGE (TARGET 10% PROFIT) ---{RESET}")
        print(f"Annual Interest Rate:          {ms.get('annual_interest_rate_pct', 10.0)}% p.a.")
        m1 = ms.get('one_month', {})
        m2 = ms.get('two_months', {})
        fy = ms.get('full_year', {})
        print(f"⚡ 1 Month Exit (30d):          {GREEN}Interest: ₹{m1.get('interest_paid'):,.2f} | Net Profit: ₹{m1.get('net_profit'):,.2f} (Retains {m1.get('profit_retained_pct')}%) | SAVES ₹{m1.get('interest_saved'):,.2f} vs Year!{RESET}")
        print(f"⏳ 2 Months Exit (60d):         {GREEN}Interest: ₹{m2.get('interest_paid'):,.2f} | Net Profit: ₹{m2.get('net_profit'):,.2f} (Retains {m2.get('profit_retained_pct')}%) | SAVES ₹{m2.get('interest_saved'):,.2f} vs Year!{RESET}")
        print(f"⚠️ 1 Year Hold (365d):         {RED}Interest: ₹{fy.get('interest_paid'):,.2f} | Net Profit: ₹{fy.get('net_profit'):,.2f} (100% wiped out by interest){RESET}")

    print(f"\n{BOLD}--- BROKER AUTO-LIQUIDATION RISK ---{RESET}")
    print(f"Broker RMS Liquidation Price:  {RED}₹{mtf['liquidation_price']}{RESET} (-{mtf['liquidation_drop_pct']}% from entry)")
    print(f"Your Safe Stop-Loss:           {YELLOW}₹{mtf['stop_loss_price']}{RESET} (-{mtf['sl_drop_pct']}% from entry)")
    if mtf["is_sl_safe_from_liquidation"]:
        print(f"Safety Cushion:                {GREEN}SAFE! Stop-loss is {mtf['safety_cushion_pct']}% ABOVE the broker liquidation trigger.{RESET}")
    else:
        print(f"Safety Cushion:                {RED}WARNING! Raise stop-loss to avoid broker auto square-off.{RESET}")

    print(f"\n{BOLD}--- HOLDING DURATION VS. NET PROFIT DECAY SCHEDULE ---{RESET}")
    print(f"{'Days Held':<12} {'Interest (₹)':<14} {'Net Profit (₹)':<16} {'Net ROI (%)':<14} {'Interest Drag':<14} {'Status':<15}")
    print("-" * 85)
    for row in mtf["schedule"]:
        roi_str = f"+{row['net_roi_pct']:.1f}%"
        drag_str = f"{row['interest_drag_pct']:.1f}%"
        print(f"{row['days']:<12} ₹{row['interest_cost']:<13,.2f} {GREEN}₹{row['net_profit']:<15,.2f}{RESET} {roi_str:<14} {drag_str:<14} {row['recommendation']:<15}")
    print("-" * 85)
    print(f"{YELLOW}* Maximum Recommended Holding Duration: {mtf['max_recommended_days']} days.{RESET}\n")


def main():
    parser = argparse.ArgumentParser(description="Top 100 Stocks & Custom Watchlist MTF Scanner, Comparison & Risk Analyzer")
    parser.add_argument("--scan", action="store_true", help="Scan stocks in selected watchlist")
    parser.add_argument("--buy-zone", action="store_true", help="Show only stocks currently in or near Buy Zone")
    parser.add_argument("--stock", type=str, help="Analyze a specific stock (e.g. NETWEB, RELIANCE, TCS, HAL)")
    parser.add_argument("--compare", nargs="+", help="Compare 2 or more stocks side-by-side")
    parser.add_argument("--capital", type=float, default=50000.0, help="Margin capital deployed (default: 50,000)")
    parser.add_argument("--watchlist", type=str, default="my_watchlist", help="Watchlist: my_watchlist (default, 22 stocks), top_100, top_50, next_50")
    parser.add_argument("--universe", type=str, choices=["50", "100", "my"], default=None, help="Legacy alias for watchlist")
    parser.add_argument("--sector", type=str, help="Filter by sector (e.g. Banking, IT, Auto, Pharma)")
    parser.add_argument("--sort", type=str, choices=["rr", "dist", "roi", "buffer"], help="Sort by: rr (Risk/Reward), dist (distance to entry), roi (15d net roi), buffer (safety cushion)")

    args = parser.parse_args()

    wl = args.watchlist
    if args.universe:
        if args.universe == "50":
            wl = "top_50"
        elif args.universe == "100":
            wl = "top_100"
        elif args.universe == "my":
            wl = "my_watchlist"

    if args.compare:
        compare_stocks(args.compare, capital=args.capital)
    elif args.stock:
        show_stock_detail(args.stock.upper(), capital=args.capital)
    else:
        stocks_count = len(get_all_stocks(wl))
        print_banner(stocks_count)
        scan_stocks(
            only_buy_zone=args.buy_zone,
            capital=args.capital,
            universe=wl,
            sector_filter=args.sector,
            sort_by=args.sort
        )


if __name__ == "__main__":
    main()
