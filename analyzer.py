"""
Technical Analysis and Buy/Sell Zone Engine.
Calculates Support & Resistance, 20 EMA, 50 SMA, 200 SMA, 14 RSI, 14 ATR,
defines dynamic Buy Zone, +10% Sell Zone, and safe Stop-Loss levels.
"""

from typing import Dict, List, Optional, Tuple
import math
from config import PROFIT_TARGET_PCT, MAX_STOP_LOSS_PCT, MIN_RISK_REWARD_RATIO


class StockAnalyzer:
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> float:
        """Calculates Exponential Moving Average for the given period."""
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        multiplier = 2.0 / (period + 1.0)
        ema = sum(prices[:period]) / period  # initial SMA
        for p in prices[period:]:
            ema = (p - ema) * multiplier + ema
        return round(ema, 2)

    @staticmethod
    def calculate_sma(prices: List[float], period: int) -> float:
        """Calculates Simple Moving Average."""
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        return round(sum(prices[-period:]) / period, 2)

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> float:
        """Calculates 14-period Relative Strength Index."""
        if len(prices) <= period:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(prices)):
            diff = prices[i] - prices[i - 1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return round(rsi, 2)

    @staticmethod
    def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Calculates Average True Range."""
        if len(closes) < 2:
            return 0.0
        trs = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
            trs.append(tr)
        if len(trs) < period:
            return round(sum(trs) / len(trs), 2)
        atr = sum(trs[:period]) / period
        for tr in trs[period:]:
            atr = (atr * (period - 1) + tr) / period
        return round(atr, 2)

    @classmethod
    def analyze_stock(cls, symbol: str, ohlc: Dict[str, List], current_ltp: Optional[float] = None) -> Dict:
        """
        Analyzes historical OHLC data to compute Buy/Sell Zones, Stop Loss, and MTF entry metrics.
        """
        closes = ohlc.get("close", [])
        highs = ohlc.get("high", [])
        lows = ohlc.get("low", [])

        if not closes:
            return {}

        ltp = float(current_ltp) if current_ltp is not None else float(closes[-1])
        ltp = round(ltp, 2)

        # Technical Indicators
        ema20 = cls.calculate_ema(closes, 20)
        sma50 = cls.calculate_sma(closes, 50)
        sma200 = cls.calculate_sma(closes, 200) if len(closes) >= 200 else cls.calculate_sma(closes, len(closes))
        rsi = cls.calculate_rsi(closes, 14)
        atr = cls.calculate_atr(highs, lows, closes, 14)

        # Recent 45-day price extremes
        lookback = min(len(closes), 45)
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        swing_high = max(recent_highs)
        swing_low = min(recent_lows)

        # Find closest support floor
        # Confluence of: EMA20, SMA50, or recent swing low
        supports = [s for s in [ema20, sma50, swing_low] if s <= ltp * 1.02]
        if supports:
            base_support = max(supports)
        else:
            base_support = ltp * 0.98

        # --- Dynamic Buy Zone ---
        # Buy Zone is an accumulation band near support [base_support * 0.995, base_support * 1.02]
        # Or if price is already in an uptrend, within 1% of current price near 20 EMA
        if ltp >= base_support:
            buy_zone_min = round(base_support * 0.995, 2)
            buy_zone_max = round(base_support * 1.02, 2)
        else:
            # Stock broke below support, lower buy zone
            buy_zone_min = round(swing_low * 0.99, 2)
            buy_zone_max = round(swing_low * 1.02, 2)

        # Reference recommended entry price (midpoint of buy zone or current LTP if in zone)
        if buy_zone_min <= ltp <= buy_zone_max:
            rec_entry = ltp
        else:
            rec_entry = round((buy_zone_min + buy_zone_max) / 2.0, 2)

        # --- Sell Zone (10% Target Strategy) ---
        # Target is ~10% profit from Entry
        target_10_pct = round(rec_entry * (1.0 + PROFIT_TARGET_PCT), 2)
        sell_zone_min = round(target_10_pct * 0.995, 2)
        sell_zone_max = round(target_10_pct * 1.015, 2)

        # --- Safe Stop Loss Level ---
        # Safe stop loss placed just below base support and 1.5 * ATR, capped at MAX_STOP_LOSS_PCT (3.5%)
        raw_sl = min(base_support * 0.985, rec_entry - (1.5 * atr))
        max_allowed_sl = rec_entry * (1.0 - MAX_STOP_LOSS_PCT)
        stop_loss = round(max(raw_sl, max_allowed_sl), 2)

        # Risk-to-Reward Ratio
        risk_per_share = max(rec_entry - stop_loss, 0.01)
        reward_per_share = target_10_pct - rec_entry
        risk_reward_ratio = round(reward_per_share / risk_per_share, 2)

        # --- Signal Classification ---
        dist_to_buy_pct = round(((ltp - buy_zone_max) / ltp) * 100.0, 2)

        if ltp <= stop_loss:
            status = "STOP_LOSS_HIT"
            status_desc = "Price below Stop-Loss. High risk, avoid entry."
            badge_color = "danger"
        elif buy_zone_min <= ltp <= buy_zone_max:
            status = "BUY_ZONE_ACTIVE"
            status_desc = "Optimal Entry Zone! Favorable 10% Risk/Reward."
            badge_color = "success"
        elif 0 < dist_to_buy_pct <= 1.8:
            status = "NEAR_BUY_ZONE"
            status_desc = f"Approaching Buy Zone ({dist_to_buy_pct}% away). Set alerts."
            badge_color = "warning"
        elif ltp >= sell_zone_min:
            status = "TARGET_ACHIEVED"
            status_desc = "10% Target reached! Book profit / Sell zone."
            badge_color = "info"
        elif ltp > buy_zone_max:
            status = "WAIT_PULLBACK"
            status_desc = f"Above entry zone (+{dist_to_buy_pct}%). Wait for dip to support."
            badge_color = "secondary"
        else:
            status = "ACCUMULATION"
            status_desc = "Near major support floor."
            badge_color = "primary"

        return {
            "symbol": symbol,
            "ltp": ltp,
            "rsi": rsi,
            "atr": atr,
            "ema20": ema20,
            "sma50": sma50,
            "sma200": sma200,
            "support": base_support,
            "resistance": swing_high,
            "buy_zone_min": buy_zone_min,
            "buy_zone_max": buy_zone_max,
            "rec_entry": rec_entry,
            "sell_zone_min": sell_zone_min,
            "sell_zone_max": sell_zone_max,
            "target_10_pct": target_10_pct,
            "stop_loss": stop_loss,
            "risk_per_share": round(risk_per_share, 2),
            "reward_per_share": round(reward_per_share, 2),
            "risk_reward_ratio": risk_reward_ratio,
            "dist_to_buy_pct": dist_to_buy_pct,
            "status": status,
            "status_desc": status_desc,
            "badge_color": badge_color
        }
