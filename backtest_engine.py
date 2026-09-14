"""
Backtesting Engine for MTF Swing Trading Strategy.
Simulates historical performance of:
1. Standard Buy Zone Strategy (+10% Target, -3.5% Stop Loss, 1-2 month hold).
2. Institutional SMC Confluence Strategy (Discount Zone + 50 SMA Trend Filter + Demand OB + ATR Stop Loss).

Accurately computes MTF leverage (4x-5x), holding duration, daily broker margin interest (10% p.a.),
gross PnL, and net in-pocket return on margin capital.
"""

import sys
import os
import math
from datetime import datetime
from typing import Dict, List, Optional, Any

from config import MTF_ANNUAL_INTEREST_RATE, PROFIT_TARGET_PCT, MAX_STOP_LOSS_PCT
from instruments import get_stock_by_symbol, _ALL_UNIQUE_STOCKS
from dhan_client import DhanClient
from analyzer import StockAnalyzer
from ai_smc_engine import SMCAnalyzer


class BacktestEngine:
    @classmethod
    def run_backtest(
        cls,
        symbol: str,
        days: int = 365,
        strategy: str = "smc_confluence",  # 'standard' or 'smc_confluence'
        capital: float = 50000.0,
        margin_pct: Optional[float] = None,
        mtf_rate: float = MTF_ANNUAL_INTEREST_RATE,
        max_hold_days: int = 45,  # ~2 calendar months
        client: Optional[DhanClient] = None
    ) -> Dict[str, Any]:
        """
        Runs a bar-by-bar realistic forward simulation for a given stock symbol.
        No forward-looking bias: entry is taken on next bar's open after signal confirmation.
        """
        if client is None:
            client = DhanClient()

        stock_info = get_stock_by_symbol(symbol)
        sec_id = stock_info["security_id"] if stock_info else None
        if not sec_id:
            for s in _ALL_UNIQUE_STOCKS:
                if s["symbol"].upper() == symbol.upper():
                    sec_id = str(s["security_id"])
                    stock_info = s
                    break

        if not sec_id:
            return {"error": f"Symbol {symbol} not found in instrument database."}

        if margin_pct is None:
            margin_pct = stock_info.get("mtf_margin_pct", 0.25) if stock_info else 0.25

        # Attempt to fetch historical daily candles
        data = client._fetch_live_nse_historical(sec_id, days)
        if not data or not data.get("close"):
            # Fallback to internal generator
            data = client.fetch_historical_daily(sec_id, days)

        if not data or len(data.get("close", [])) < 55:
            return {"error": f"Insufficient historical price data for {symbol}."}

        closes = data["close"]
        opens = data.get("open", closes)
        highs = data.get("high", closes)
        lows = data.get("low", closes)
        timestamps = data.get("timestamp", [0] * len(closes))
        n = len(closes)

        user_cash = capital * margin_pct
        loan_amount = capital * (1.0 - margin_pct)
        annual_rate = mtf_rate if mtf_rate <= 1.0 else (mtf_rate / 100.0)
        daily_interest_rate = annual_rate / 365.0

        trades: List[Dict[str, Any]] = []
        i = 50  # Warm up period for moving averages and ATR

        while i < n - 1:
            slice_ohlc = {
                "close": closes[: i + 1],
                "open": opens[: i + 1],
                "high": highs[: i + 1],
                "low": lows[: i + 1],
            }
            res = StockAnalyzer.analyze_stock(symbol, slice_ohlc, current_ltp=closes[i])

            signal_triggered = False

            if strategy == "standard":
                # Original trigger: Stock status in BUY_ZONE_ACTIVE
                signal_triggered = res.get("status") == "BUY_ZONE_ACTIVE"
            else:
                # Enhanced SMC & Trend Confluence Strategy
                # 1. Macro Trend: Price >= 98% of 50 SMA (avoids falling knives during secular downtrends)
                sma50 = res.get("sma50", 0)
                is_uptrend = closes[i] >= sma50 * 0.98

                # 2. SMC Alignment: In Discount Zone (Smart Money Accumulation)
                is_discount = res.get("price_position") == "Discount" or closes[i] <= res.get("buy_zone_max", 0)

                # 3. Buy Zone Active or Near Zone with favorable momentum
                is_buy_zone = res.get("status") in ["BUY_ZONE_ACTIVE", "NEAR_BUY_ZONE"]

                signal_triggered = is_uptrend and is_discount and is_buy_zone

            if signal_triggered:
                # Enter trade on next day's open
                entry_idx = i + 1
                entry_price = opens[entry_idx] if entry_idx < n else closes[i]

                if strategy == "standard":
                    target_price = round(entry_price * (1.0 + PROFIT_TARGET_PCT), 2)  # +10%
                    stop_loss = round(entry_price * (1.0 - MAX_STOP_LOSS_PCT), 2)      # -3.5%
                else:
                    # Dynamic ATR Stop Loss: allows normal daily swing noise (4% - 5% cushion)
                    atr = res.get("atr", entry_price * 0.025)
                    sl_dist = max(atr * 1.5, entry_price * 0.04)
                    stop_loss = round(max(entry_price - sl_dist, entry_price * 0.95), 2)  # max 5% SL
                    target_price = round(entry_price * (1.0 + PROFIT_TARGET_PCT), 2)      # +10%

                exit_idx = None
                exit_price = None
                outcome = None

                # Forward simulate subsequent bars up to max_hold_days (45 bars ~ 2 months)
                for k in range(entry_idx, min(entry_idx + max_hold_days, n)):
                    bar_high = highs[k]
                    bar_low = lows[k]

                    # 1. Target Hit check (+10%)
                    if bar_high >= target_price:
                        exit_idx = k
                        exit_price = target_price
                        outcome = "TARGET_HIT"
                        break
                    # 2. Stop Loss Hit check
                    elif bar_low <= stop_loss:
                        exit_idx = k
                        exit_price = stop_loss
                        outcome = "STOP_LOSS_HIT"
                        break

                # 3. Time Exit if neither hit within 2 months (max_hold_days)
                if exit_idx is None:
                    exit_idx = min(entry_idx + max_hold_days - 1, n - 1)
                    exit_price = closes[exit_idx]
                    outcome = "TIME_EXIT"

                days_held = max(exit_idx - entry_idx, 1)
                gross_return_pct = round(((exit_price - entry_price) / entry_price) * 100.0, 2)
                gross_pnl = round(capital * (gross_return_pct / 100.0), 2)

                # Calendar days factor (~1.4 calendar days per trading bar)
                calendar_days = round(days_held * 1.4)
                interest_paid = round(loan_amount * daily_interest_rate * calendar_days, 2)
                net_pnl = round(gross_pnl - interest_paid, 2)
                net_roi_on_capital = round((net_pnl / user_cash) * 100.0, 2)

                entry_date = (
                    datetime.fromtimestamp(timestamps[entry_idx]).strftime("%Y-%m-%d")
                    if timestamps[entry_idx]
                    else f"Day {entry_idx}"
                )
                exit_date = (
                    datetime.fromtimestamp(timestamps[exit_idx]).strftime("%Y-%m-%d")
                    if timestamps[exit_idx]
                    else f"Day {exit_idx}"
                )

                trades.append({
                    "trade_num": len(trades) + 1,
                    "entry_date": entry_date,
                    "exit_date": exit_date,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "target_price": target_price,
                    "stop_loss": stop_loss,
                    "outcome": outcome,
                    "days_held": days_held,
                    "calendar_days": calendar_days,
                    "gross_return_pct": gross_return_pct,
                    "gross_pnl": gross_pnl,
                    "interest_paid": interest_paid,
                    "net_pnl": net_pnl,
                    "net_roi_on_capital": net_roi_on_capital
                })

                # Move pointer to day after trade exit
                i = exit_idx + 1
            else:
                i += 1

        # Calculate performance statistics
        total_trades = len(trades)
        wins = [t for t in trades if t["net_pnl"] > 0]
        losses = [t for t in trades if t["net_pnl"] < 0]
        target_hits = [t for t in trades if t["outcome"] == "TARGET_HIT"]
        sl_hits = [t for t in trades if t["outcome"] == "STOP_LOSS_HIT"]
        time_exits = [t for t in trades if t["outcome"] == "TIME_EXIT"]

        win_rate = round((len(wins) / total_trades) * 100.0, 1) if total_trades > 0 else 0.0
        total_gross_pnl = round(sum(t["gross_pnl"] for t in trades), 2)
        total_interest = round(sum(t["interest_paid"] for t in trades), 2)
        total_net_pnl = round(sum(t["net_pnl"] for t in trades), 2)

        gross_wins = sum(t["gross_pnl"] for t in wins)
        gross_losses = abs(sum(t["gross_pnl"] for t in losses))
        profit_factor = round(gross_wins / max(gross_losses, 1.0), 2) if gross_losses > 0 else (99.0 if gross_wins > 0 else 0.0)

        avg_days_held = round(sum(t["days_held"] for t in trades) / total_trades, 1) if total_trades > 0 else 0.0
        avg_cal_days = round(sum(t["calendar_days"] for t in trades) / total_trades, 1) if total_trades > 0 else 0.0
        total_margin_roi = round((total_net_pnl / user_cash) * 100.0, 2) if user_cash > 0 else 0.0

        return {
            "symbol": symbol,
            "company_name": stock_info.get("name", symbol) if stock_info else symbol,
            "sector": stock_info.get("sector", "General") if stock_info else "General",
            "strategy": strategy,
            "tested_bars": n,
            "trade_capital": capital,
            "user_cash_margin": user_cash,
            "mtf_loan_amount": loan_amount,
            "leverage": round(1.0 / margin_pct, 1),
            "total_trades": total_trades,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "target_hits": len(target_hits),
            "stop_loss_hits": len(sl_hits),
            "time_exits": len(time_exits),
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "avg_trading_days": avg_days_held,
            "avg_calendar_days": avg_cal_days,
            "total_gross_pnl": total_gross_pnl,
            "total_mtf_interest": total_interest,
            "total_net_pnl": total_net_pnl,
            "total_margin_roi_pct": total_margin_roi,
            "trades": trades
        }


if __name__ == "__main__":
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["CGPOWER", "JIOFIN", "NETWEB"]
    print("==========================================================================")
    print("🚀 MTF 1-2 MONTH STRATEGY BACKTEST ENGINE")
    print(f"   Stocks: {', '.join(symbols)} | Capital: ₹50,000 per trade | MTF Rate: 10% p.a.")
    print("==========================================================================\n")

    for sym in symbols:
        res = BacktestEngine.run_backtest(sym, strategy="smc_confluence")
        if "error" in res:
            print(f"❌ {sym}: {res['error']}")
            continue

        print(f"📊 {res['symbol']} ({res['company_name']}) — Sector: {res['sector']}")
        print(f"   Trades: {res['total_trades']} | Win Rate: {res['win_rate_pct']}% | Profit Factor: {res['profit_factor']}")
        print(f"   Avg Hold: {res['avg_trading_days']} trading days (~{res['avg_calendar_days']} calendar days)")
        print(f"   Gross PnL: ₹{res['total_gross_pnl']:+,.2f} | MTF Interest Paid: ₹{res['total_mtf_interest']:,.2f}")
        print(f"   Net In-Pocket Profit: ₹{res['total_net_pnl']:+,.2f} (Net Margin ROI: {res['total_margin_roi_pct']:+}%)")
        print("   Recent Trades:")
        for t in res["trades"][-5:]:
            print(f"     • #{t['trade_num']}: {t['entry_date']} -> {t['exit_date']} | Entry: ₹{t['entry_price']} -> Exit: ₹{t['exit_price']} | {t['outcome']} | Held: {t['days_held']}d | Net: ₹{t['net_pnl']:+,.2f} ({t['net_roi_on_capital']:+}%)")
        print("-" * 74)
