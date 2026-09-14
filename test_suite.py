"""
Comprehensive Test Suite for Top 50 Stocks MTF Trading System.
Verifies MTF mathematics, broker auto-liquidation triggers, technical indicator calculations,
and dashboard server endpoints.
"""

import unittest
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

from config import (
    MTF_ANNUAL_INTEREST_RATE,
    MTF_MAINTENANCE_MARGIN_PCT,
    PROFIT_TARGET_PCT,
    MAX_STOP_LOSS_PCT
)
from instruments import get_all_stocks, get_stock_by_symbol, get_security_id_list
from analyzer import StockAnalyzer
from mtf_risk_engine import MTFRiskEngine
from dashboard import DashboardRequestHandler


class TestMTFMathematics(unittest.TestCase):
    def test_trade_plan_leverage_and_profit(self):
        entry_price = 1000.0
        capital = 25000.0
        margin_pct = 0.25  # 4x leverage

        plan = MTFRiskEngine.calculate_trade_plan(
            entry_price=entry_price,
            capital=capital,
            margin_pct=margin_pct,
            target_pct=0.10,
            stop_loss_price=965.0
        )

        # 4x leverage means total trade value is approx 100,000
        self.assertEqual(plan["leverage"], 4.0)
        self.assertEqual(plan["quantity"], 100)
        self.assertEqual(plan["position_value"], 100000.0)
        self.assertEqual(plan["invested_margin"], 25000.0)
        self.assertEqual(plan["borrowed_amount"], 75000.0)

        # 10% Target
        self.assertEqual(plan["target_price"], 1100.0)
        self.assertEqual(plan["gross_profit"], 10000.0)
        self.assertEqual(plan["gross_roi_pct"], 40.0)  # 40% ROI on margin!

    def test_daily_interest_calculation(self):
        entry_price = 1000.0
        capital = 25000.0
        plan = MTFRiskEngine.calculate_trade_plan(
            entry_price=entry_price,
            capital=capital,
            margin_pct=0.25,
            annual_interest_rate=0.16
        )
        # Borrowed = 75,000. Daily interest = 75,000 * 0.16 / 365 = 32.8767 -> 32.88
        expected_daily_interest = round(75000.0 * (0.16 / 365.0), 2)
        self.assertEqual(plan["daily_interest_cost"], expected_daily_interest)

        # 15 days interest check in schedule
        sched_15 = next(item for item in plan["schedule"] if item["days"] == 15)
        self.assertEqual(sched_15["interest_cost"], round(expected_daily_interest * 15, 2))
        self.assertTrue(sched_15["net_profit"] > 8800.0)  # Over 8.8k profit retained after 15 days, accounting for interest and statutory charges

    def test_broker_liquidation_trigger_and_sl_safety(self):
        entry_price = 1000.0
        capital = 25000.0
        margin_pct = 0.25  # 25% margin
        maintenance_margin_pct = 0.15  # 15% broker maintenance margin

        plan = MTFRiskEngine.calculate_trade_plan(
            entry_price=entry_price,
            capital=capital,
            margin_pct=margin_pct,
            maintenance_margin_pct=maintenance_margin_pct,
            stop_loss_price=965.0  # 3.5% SL
        )

        # Borrowed per share = 750. Liquidation price = 750 / (1 - 0.15) = 750 / 0.85 = 882.35
        expected_liq_price = round(750.0 / 0.85, 2)
        self.assertEqual(plan["liquidation_price"], expected_liq_price)

        # Verify mathematical identity: at liquidation price, remaining equity / value == maintenance margin
        liq_val = expected_liq_price * plan["quantity"]
        remaining_equity = plan["invested_margin"] - ((entry_price - expected_liq_price) * plan["quantity"])
        actual_equity_ratio = remaining_equity / liq_val
        self.assertAlmostEqual(actual_equity_ratio, maintenance_margin_pct, places=2)

        # User's Stop Loss (965) is strictly above broker liquidation (882.35)
        self.assertTrue(plan["is_sl_safe_from_liquidation"])
        self.assertTrue(plan["stop_loss_price"] > plan["liquidation_price"])


class TestStockAnalyzer(unittest.TestCase):
    def setUp(self):
        # Synthetic 50 days of ascending prices
        self.closes = [100.0 + i for i in range(50)]
        self.highs = [c + 2.0 for c in self.closes]
        self.lows = [c - 2.0 for c in self.closes]
        self.ohlc = {
            "close": self.closes,
            "high": self.highs,
            "low": self.lows
        }

    def test_indicators(self):
        ema20 = StockAnalyzer.calculate_ema(self.closes, 20)
        sma50 = StockAnalyzer.calculate_sma(self.closes, 50)
        rsi = StockAnalyzer.calculate_rsi(self.closes, 14)
        atr = StockAnalyzer.calculate_atr(self.highs, self.lows, self.closes, 14)

        self.assertTrue(ema20 > 0)
        self.assertTrue(sma50 > 0)
        self.assertTrue(0 <= rsi <= 100)
        self.assertTrue(atr > 0)

    def test_buy_and_sell_zones(self):
        analysis = StockAnalyzer.analyze_stock("TEST", self.ohlc, current_ltp=150.0)

        # Buy Zone should be around support
        self.assertTrue(analysis["buy_zone_min"] < analysis["buy_zone_max"])
        
        # 10% Target Strategy
        expected_target = round(analysis["rec_entry"] * (1.0 + PROFIT_TARGET_PCT), 2)
        self.assertEqual(analysis["target_10_pct"], expected_target)

        # Stop loss should not exceed max allowed risk (3.5%)
        max_allowed_drop = round(analysis["rec_entry"] * (1.0 - MAX_STOP_LOSS_PCT), 2)
        self.assertTrue(analysis["stop_loss"] >= max_allowed_drop)

        # Risk-to-reward ratio should be healthy (>= 2.5:1)
        self.assertTrue(analysis["risk_reward_ratio"] >= 2.5)


    def test_milestone_1_to_2m_calculation(self):
        # User scenario: 50,000 capital, 10% target gain, 10% annual interest rate
        plan = MTFRiskEngine.calculate_trade_plan(
            entry_price=1000.0,
            capital=50000.0,
            margin_pct=1.0,  # 1x leverage to directly test 50k capital
            target_pct=0.10,
            annual_interest_rate=0.10
        )
        ms = plan["milestone_1_to_2m"]
        self.assertEqual(ms["annual_interest_rate_pct"], 10.0)
        self.assertAlmostEqual(ms["annual_interest_cost"], 0.0) # borrowed is 0 at 1x leverage

        # Test with 4x leverage (capital 50,000, margin 25% = borrowed 150,000)
        plan_4x = MTFRiskEngine.calculate_trade_plan(
            entry_price=1000.0,
            capital=50000.0,
            margin_pct=0.25,
            target_pct=0.10,
            annual_interest_rate=0.10
        )
        ms_4x = plan_4x["milestone_1_to_2m"]
        self.assertIn("one_month", ms_4x)
        self.assertIn("two_months", ms_4x)
        self.assertIn("full_year", ms_4x)
        self.assertTrue(ms_4x["one_month"]["net_profit"] > ms_4x["two_months"]["net_profit"])
        self.assertTrue(ms_4x["one_month"]["interest_saved"] > 0)


class TestInstrumentsUniverse(unittest.TestCase):
    def test_user_watchlist_loading(self):
        from instruments import USER_WATCHLIST_STOCKS, get_available_watchlists
        self.assertEqual(len(USER_WATCHLIST_STOCKS), 22, "User custom watchlist should have 22 stocks")
        wl_stocks = get_all_stocks("my_watchlist")
        self.assertEqual(len(wl_stocks), 22)

        # Check key stocks from screenshots
        symbols = [s["symbol"] for s in wl_stocks]
        for expected in ["NETWEB", "NEULANDLAB", "CGPOWER", "AADHARHFC", "JSWCEMENT", "JIOFIN", "CELLO"]:
            self.assertIn(expected, symbols)

        # Check watchlists registry
        watchlists = get_available_watchlists()
        self.assertEqual(len(watchlists), 4)
        wl_ids = [w["id"] for w in watchlists]
        self.assertIn("my_watchlist", wl_ids)
        self.assertIn("top_100", wl_ids)

    def test_universe_loading(self):
        stocks_100 = get_all_stocks("TOP_100")
        self.assertEqual(len(stocks_100), 100, "Top 100 universe should have 100 stocks")

        stocks_50 = get_all_stocks("TOP_50")
        self.assertEqual(len(stocks_50), 50, "Top 50 universe should have 50 stocks")

        symbols = [s["symbol"] for s in stocks_100]
        self.assertEqual(len(set(symbols)), 100, "Duplicate symbols found in universe")

        # Verify key stocks exist across Nifty 50 and Nifty Next 50
        for expected in ["RELIANCE", "TCS", "HDFCBANK", "HAL", "ZOMATO", "TRENT", "BEL"]:
            self.assertIn(expected, symbols)

        # Verify all security IDs are non-empty
        sec_ids = get_security_id_list("TOP_100")
        self.assertEqual(len(sec_ids), 100)
        for sid in sec_ids:
            self.assertTrue(isinstance(sid, int) and sid > 0)


class TestDashboardAPI(unittest.TestCase):
    def test_get_stocks_data_structure(self):
        from dashboard import get_analyzed_stocks
        data = get_analyzed_stocks(universe="TOP_100", force_refresh=True)
        self.assertIn("stocks", data)
        self.assertIn("summary", data)
        self.assertEqual(len(data["stocks"]), 100)
        
        # Verify first stock has all required dashboard fields
        sample = data["stocks"][0]
        required_fields = [
            "symbol", "ltp", "buy_zone_min", "buy_zone_max", "rec_entry",
            "target_10_pct", "stop_loss", "status", "mtf_liquidation_price",
            "mtf_daily_interest", "mtf_gross_profit", "safety_buffer", "net_roi_15d"
        ]
        for field in required_fields:
            self.assertIn(field, sample, f"Missing {field} in dashboard stock data")

    def test_mtf_calc_api_logic(self):
        plan = MTFRiskEngine.calculate_trade_plan(
            entry_price=2500.0,
            capital=100000.0,
            margin_pct=0.25,
            stop_loss_price=2420.0
        )
        self.assertEqual(plan["leverage"], 4.0)
        self.assertEqual(plan["gross_roi_pct"], 40.0)
        self.assertTrue("liquidation_price" in plan)
        self.assertTrue(plan["is_sl_safe_from_liquidation"])

    def test_comparison_logic(self):
        stocks = ["RELIANCE", "TCS", "HAL"]
        for sym in stocks:
            stock = get_stock_by_symbol(sym)
            self.assertIsNotNone(stock, f"Stock {sym} should exist for comparison")


class TestPWAAndMobile(unittest.TestCase):
    def test_pwa_static_assets_exist(self):
        from pathlib import Path
        static_dir = Path(__file__).parent / "static"
        self.assertTrue((static_dir / "manifest.json").is_file(), "manifest.json missing")
        self.assertTrue((static_dir / "sw.js").is_file(), "sw.js missing")
        self.assertTrue((static_dir / "icon.svg").is_file(), "icon.svg missing")
        self.assertTrue((static_dir / "icon-192.png").is_file(), "icon-192.png missing")
        self.assertTrue((static_dir / "icon-512.png").is_file(), "icon-512.png missing")

    def test_pwa_manifest_structure(self):
        from pathlib import Path
        manifest_path = Path(__file__).parent / "static" / "manifest.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest.get("display"), "standalone")
        self.assertIn("icons", manifest)
        self.assertTrue(len(manifest["icons"]) >= 2)
        sizes = [icon.get("sizes") for icon in manifest["icons"]]
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)

    def test_mobile_view_and_pwa_elements_in_template(self):
        from pathlib import Path
        template_path = Path(__file__).parent / "templates" / "index.html"
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Check PWA tags
        self.assertIn('rel="manifest"', html)
        self.assertIn('href="/manifest.json"', html)
        self.assertIn('viewport-fit=cover', html)
        self.assertIn('apple-mobile-web-app-capable', html)

        # Check mobile card and toggle elements
        self.assertIn('id="btnViewCards"', html)
        self.assertIn('id="btnViewTable"', html)
        self.assertIn('id="stocksCardsContainer"', html)
        self.assertIn('id="stocksTableWrapper"', html)

        # Check PWA install elements
        self.assertIn('id="pwaInstallBtn"', html)
        self.assertIn('id="pwaMobileBanner"', html)
        self.assertIn('id="iosInstallModal"', html)
        self.assertIn('renderCards', html)
        self.assertIn('installPWA', html)

        # Check Light / Dark mode toggle and mobile header
        self.assertIn('id="themeToggleBtn"', html)
        self.assertIn('toggleTheme', html)
        self.assertIn('app-header', html)
        self.assertIn('id="watchlistSelectMobile"', html)

        # Check PIN Security & SMC UI elements
        self.assertIn('id="pinAuthOverlay"', html)
        self.assertIn('id="lockPortalBtn"', html)
        self.assertIn('id="smcModal"', html)
        self.assertIn('openSmcModal', html)
        self.assertIn('verifyPin', html)
        self.assertIn('lockPortal', html)


class TestPINSecurityAndAuth(unittest.TestCase):
    def test_default_pin_is_654000(self):
        from config import PORTAL_PIN, verify_portal_pin
        self.assertEqual(PORTAL_PIN, "654000")
        self.assertTrue(verify_portal_pin("654000"))
        self.assertTrue(verify_portal_pin(" 654000 "))
        self.assertFalse(verify_portal_pin("123456"))
        self.assertFalse(verify_portal_pin("254214"))
        self.assertFalse(verify_portal_pin(""))

    def test_dashboard_pin_endpoints(self):
        # Test request handler directly with mock
        from dashboard import DashboardRequestHandler
        from unittest.mock import MagicMock
        import io

        # 1. Test invalid PIN POST
        handler = MagicMock(spec=DashboardRequestHandler)
        handler.path = "/api/auth/pin-verify"
        handler.headers = {"Content-Length": "19"}
        handler.rfile = io.BytesIO(b'{"pin": "000000"}')
        sent_jsons = []
        handler._send_json = lambda data, status=200, cookie_header=None: sent_jsons.append((data, status, cookie_header))
        DashboardRequestHandler.do_POST(handler)
        self.assertEqual(len(sent_jsons), 1)
        self.assertEqual(sent_jsons[0][1], 401)
        self.assertFalse(sent_jsons[0][0]["success"])

        # 2. Test valid PIN POST (654000)
        sent_jsons.clear()
        handler.rfile = io.BytesIO(b'{"pin": "654000"}')
        DashboardRequestHandler.do_POST(handler)
        self.assertEqual(len(sent_jsons), 1)
        self.assertEqual(sent_jsons[0][1], 200)
        self.assertTrue(sent_jsons[0][0]["success"])
        self.assertIn("mtf_pin_auth=654000", sent_jsons[0][2])


class TestSMCEngineAndAI(unittest.TestCase):
    def test_smc_order_block_detection(self):
        from analyzer import SMCAnalyzer
        opens = [100.0, 102.0, 98.0, 104.0, 108.0]
        highs = [101.0, 103.0, 99.0, 106.0, 110.0]
        lows = [99.0, 97.0, 95.0, 100.0, 105.0]
        closes = [101.0, 98.0, 96.0, 105.0, 109.0]

        obs = SMCAnalyzer.detect_order_blocks(opens, highs, lows, closes)
        self.assertIn("bullish_ob", obs)
        bull_ob = obs["bullish_ob"]
        self.assertIsNotNone(bull_ob)
        self.assertEqual(bull_ob["low"], 95.0)

    def test_smc_pd_array_discount_vs_premium(self):
        from analyzer import SMCAnalyzer
        highs = [100.0, 110.0, 120.0]
        lows = [80.0, 85.0, 90.0]

        # Range is 80 to 120. Midpoint = 100.
        # Below 100 -> Discount
        discount_res = SMCAnalyzer.calculate_pd_array(highs, lows, 88.0)
        self.assertEqual(discount_res["price_position"], "Discount")

        # Above 100 -> Premium
        premium_res = SMCAnalyzer.calculate_pd_array(highs, lows, 115.0)
        self.assertEqual(premium_res["price_position"], "Premium")

    def test_mtf_holding_advantage_calculation(self):
        from ai_smc_engine import AISmcEngine
        # ₹50,000 capital, 10% target = ₹5,000 profit
        adv = AISmcEngine.calculate_mtf_holding_advantage(1000.0, 1100.0, 50000.0)
        sched = adv["direct_schedule"]
        self.assertEqual(len(sched), 3)

        # 15 days
        self.assertEqual(sched[0]["days"], 15)
        self.assertAlmostEqual(sched[0]["interest_paid"], 205.48, delta=1.0)
        self.assertTrue(sched[0]["net_profit"] > 4700.0)

        # 30 days (1 month)
        self.assertEqual(sched[1]["days"], 30)
        self.assertAlmostEqual(sched[1]["interest_paid"], 410.96, delta=1.0)
        self.assertTrue(sched[1]["net_profit"] > 4500.0)

        # 60 days (2 months)
        self.assertEqual(sched[2]["days"], 60)
        self.assertAlmostEqual(sched[2]["interest_paid"], 821.92, delta=1.0)
        self.assertTrue(sched[2]["net_profit"] > 4100.0)

        # Verify summary reflects holding profit advantage
        self.assertIn("₹50,000", adv["user_summary"])
        self.assertIn("₹5,000", adv["user_summary"])

    def test_backtest_engine_execution(self):
        from backtest_engine import BacktestEngine
        # Run backtest on a known stock
        res = BacktestEngine.run_backtest("NETWEB", days=120, strategy="smc_confluence")
        self.assertNotIn("error", res)
        self.assertEqual(res["symbol"], "NETWEB")
        self.assertIn("total_trades", res)
        self.assertIn("win_rate_pct", res)
        self.assertIn("total_net_pnl", res)
        self.assertIn("total_mtf_interest", res)
        self.assertGreaterEqual(res["total_trades"], 0)


if __name__ == "__main__":
    unittest.main()


