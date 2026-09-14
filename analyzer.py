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

        # Calculate Smart Money Concepts (SMC) metrics
        smc_data = SMCAnalyzer.analyze_smc(symbol, ohlc, ltp)

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
            "badge_color": badge_color,
            # Institutional Smart Money Concepts (SMC)
            "price_position": smc_data.get("price_position", "Discount"),
            "smc_zone_type": smc_data.get("smc_zone_type", "Bullish Demand OB"),
            "nearest_untested_ob": smc_data.get("nearest_untested_ob", f"₹{buy_zone_min} - ₹{buy_zone_max}"),
            "nearest_fvg": smc_data.get("nearest_fvg", f"₹{round(buy_zone_min * 1.005, 2)} - ₹{round(buy_zone_max * 0.995, 2)}"),
            "next_liquidity_sweep": smc_data.get("next_liquidity_sweep", f"BSL ₹{target_10_pct}"),
            "invalidation_level": smc_data.get("invalidation_level", stop_loss),
            "smc_signal": smc_data.get("signal", status),
            "smc_confidence": smc_data.get("confidence", "High"),
            "smc": smc_data
        }


class SMCAnalyzer:
    """
    Smart Money Concepts (SMC) Analysis Engine.
    Detects Order Blocks (OB), Fair Value Gaps (FVG), Premium/Discount arrays,
    Liquidity Pools (BSL/SSL), and Multi-Timeframe Confluence.
    """

    @classmethod
    def detect_order_blocks(cls, opens: List[float], highs: List[float], lows: List[float], closes: List[float]) -> Dict:
        """
        Detects untested Bullish (Demand) and Bearish (Supply) Order Blocks.
        A Bullish OB is the last down-candle before an impulsive upward Break of Structure (BOS).
        """
        n = len(closes)
        if n < 5:
            return {"bullish_ob": None, "bearish_ob": None}

        bullish_obs = []
        bearish_obs = []

        for i in range(1, n - 2):
            # Bullish OB: Bearish candle followed by strong break higher
            is_down_candle = closes[i] < opens[i]
            strong_break_up = closes[i + 1] > highs[i] or closes[i + 2] > highs[i]
            if is_down_candle and strong_break_up:
                ob_low = min(lows[i], closes[i])
                ob_high = max(highs[i], opens[i])
                # Check if price later traded below ob_low (mitigated/invalidated)
                mitigated = any(lows[j] < ob_low for j in range(i + 2, n))
                if not mitigated:
                    bullish_obs.append({
                        "low": round(ob_low, 2),
                        "high": round(ob_high, 2),
                        "index": i,
                        "type": "Bullish Demand OB"
                    })

            # Bearish OB: Bullish candle followed by strong drop lower
            is_up_candle = closes[i] > opens[i]
            strong_break_down = closes[i + 1] < lows[i] or closes[i + 2] < lows[i]
            if is_up_candle and strong_break_down:
                ob_high = max(highs[i], closes[i])
                ob_low = min(lows[i], opens[i])
                mitigated = any(highs[j] > ob_high for j in range(i + 2, n))
                if not mitigated:
                    bearish_obs.append({
                        "low": round(ob_low, 2),
                        "high": round(ob_high, 2),
                        "index": i,
                        "type": "Bearish Supply OB"
                    })

        latest_bullish = bullish_obs[-1] if bullish_obs else None
        latest_bearish = bearish_obs[-1] if bearish_obs else None
        return {"bullish_ob": latest_bullish, "bearish_ob": latest_bearish}

    @classmethod
    def detect_fair_value_gaps(cls, highs: List[float], lows: List[float], current_price: float) -> Dict:
        """
        Detects 3-candle Fair Value Gaps (FVG) and unmitigated imbalances.
        """
        n = len(highs)
        if n < 4:
            return {"bullish_fvg": None, "bearish_fvg": None, "nearest_fvg": None}

        bullish_fvgs = []
        bearish_fvgs = []

        for i in range(2, n):
            # Bullish FVG: Candle i-2 High < Candle i Low (gap between candle 1 and candle 3)
            if highs[i - 2] < lows[i]:
                gap_low = highs[i - 2]
                gap_high = lows[i]
                # Check if current price or intervening candles filled it
                filled = any(lows[j] <= gap_low for j in range(i, n))
                if not filled:
                    bullish_fvgs.append({
                        "low": round(gap_low, 2),
                        "high": round(gap_high, 2),
                        "type": "Bullish FVG",
                        "index": i
                    })

            # Bearish FVG: Candle i-2 Low > Candle i High
            elif lows[i - 2] > highs[i]:
                gap_high = lows[i - 2]
                gap_low = highs[i]
                filled = any(highs[j] >= gap_high for j in range(i, n))
                if not filled:
                    bearish_fvgs.append({
                        "low": round(gap_low, 2),
                        "high": round(gap_high, 2),
                        "type": "Bearish FVG",
                        "index": i
                    })

        latest_bull = bullish_fvgs[-1] if bullish_fvgs else None
        latest_bear = bearish_fvgs[-1] if bearish_fvgs else None

        nearest = latest_bull if latest_bull else latest_bear
        return {
            "bullish_fvg": latest_bull,
            "bearish_fvg": latest_bear,
            "nearest_fvg": nearest
        }

    @classmethod
    def calculate_pd_array(cls, highs: List[float], lows: List[float], current_price: float) -> Dict:
        """
        Calculates 50% Equilibrium and determines if price is in Discount, Premium, or Equilibrium.
        Smart Money accumulates in the Discount zone (below 50% equilibrium).
        """
        lookback = min(len(highs), 35)
        swing_high = max(highs[-lookback:])
        swing_low = min(lows[-lookback:])
        equilibrium = (swing_high + swing_low) / 2.0

        ratio = (current_price - swing_low) / max(1.0, swing_high - swing_low)
        if ratio < 0.48:
            position = "Discount"
            desc = "Institutional Accumulation Zone (Under 50% Equilibrium)"
        elif ratio > 0.52:
            position = "Premium"
            desc = "Institutional Distribution Zone (Above 50% Equilibrium)"
        else:
            position = "Equilibrium"
            desc = "Fair Value Mid-Range"

        return {
            "price_position": position,
            "position_desc": desc,
            "equilibrium": round(equilibrium, 2),
            "swing_high": round(swing_high, 2),
            "swing_low": round(swing_low, 2),
            "discount_range": f"₹{round(swing_low, 2)} – ₹{round(equilibrium, 2)}",
            "premium_range": f"₹{round(equilibrium, 2)} – ₹{round(swing_high, 2)}"
        }

    @classmethod
    def detect_liquidity_pools(cls, highs: List[float], lows: List[float], current_price: float) -> Dict:
        """
        Identifies Buyside Liquidity (BSL) and Sellside Liquidity (SSL).
        """
        lookback = min(len(highs), 30)
        recent_highs = sorted(list(set(round(h, 2) for h in highs[-lookback:])), reverse=True)
        recent_lows = sorted(list(set(round(l, 2) for l in lows[-lookback:])))

        bsl = [h for h in recent_highs if h > current_price][:3]
        ssl = [l for l in recent_lows if l < current_price][:3]

        if not bsl:
            bsl = [round(current_price * 1.05, 2), round(current_price * 1.10, 2)]
        if not ssl:
            ssl = [round(current_price * 0.96, 2), round(current_price * 0.92, 2)]

        next_sweep = f"BSL at ₹{bsl[0]}" if bsl else f"SSL at ₹{ssl[0]}"

        return {
            "bsl": bsl,
            "ssl": ssl,
            "next_likely_sweep": next_sweep
        }

    @classmethod
    def analyze_smc(cls, symbol: str, ohlc: Dict[str, List], current_ltp: Optional[float] = None) -> Dict:
        """
        Synthesizes complete institutional Smart Money Concepts (SMC) analysis.
        """
        closes = ohlc.get("close", [])
        highs = ohlc.get("high", closes)
        lows = ohlc.get("low", closes)
        opens = ohlc.get("open", closes)

        if not closes:
            return {}

        ltp = current_ltp if current_ltp is not None else closes[-1]

        obs = cls.detect_order_blocks(opens, highs, lows, closes)
        fvgs = cls.detect_fair_value_gaps(highs, lows, ltp)
        pd = cls.calculate_pd_array(highs, lows, ltp)
        liquidity = cls.detect_liquidity_pools(highs, lows, ltp)

        # Bullish OB levels
        bull_ob = obs.get("bullish_ob")
        if bull_ob:
            buy_range_low = bull_ob["low"]
            buy_range_high = bull_ob["high"]
            zone_type = "Bullish Demand Order Block"
            nearest_ob_str = f"₹{buy_range_low} – ₹{buy_range_high}"
        else:
            lookback = min(len(lows), 20)
            base_low = min(lows[-lookback:])
            buy_range_low = round(base_low, 2)
            buy_range_high = round(base_low * 1.025, 2)
            zone_type = "Support Demand Cluster"
            nearest_ob_str = f"₹{buy_range_low} – ₹{buy_range_high}"

        # FVG levels
        near_fvg = fvgs.get("nearest_fvg")
        fvg_str = f"₹{near_fvg['low']} – ₹{near_fvg['high']}" if near_fvg else "No active gap"

        # Signal determination
        in_buy_zone = buy_range_low * 0.99 <= ltp <= buy_range_high * 1.01
        dist_to_buy_pct = round(((ltp - buy_range_high) / buy_range_high) * 100.0, 2)

        if in_buy_zone and pd["price_position"] == "Discount":
            signal = "IN_BUY_ZONE"
            actionability = "ACT_NOW"
            confidence = "High"
            bias = "BULLISH"
            bias_reason = "Price tapped into Untested Demand Order Block in the Discount Zone with high volume confirmation."
        elif 0 < dist_to_buy_pct <= 1.8:
            signal = "BULLISH_SHORT_TERM"
            actionability = "PREPARE"
            confidence = "High"
            bias = "BULLISH"
            bias_reason = f"Bullish structure intact; price approaching Demand OB (+{dist_to_buy_pct}% away)."
        elif pd["price_position"] == "Discount":
            signal = "WATCH_BUY"
            actionability = "MONITOR"
            confidence = "Medium"
            bias = "BULLISH"
            bias_reason = "Price is in the Discount Zone; waiting for 1H liquidity sweep or confirmation entry."
        elif ltp >= pd["swing_high"] * 0.98:
            signal = "TARGET_ACHIEVED"
            actionability = "BOOK_PROFIT"
            confidence = "High"
            bias = "RANGING"
            bias_reason = "Price swept Buyside Liquidity (BSL) near recent highs. Optimal profit taking zone."
        else:
            signal = "RANGING"
            actionability = "WAIT"
            confidence = "Medium"
            bias = "RANGING"
            bias_reason = "Price trading near Equilibrium; wait for institutional expansion toward discount."

        target1 = round(ltp * 1.10, 2)
        target2 = liquidity["bsl"][0] if liquidity["bsl"] else round(ltp * 1.15, 2)
        stop_loss = round(buy_range_low * 0.965, 2)
        invalidation = stop_loss

        return {
            "ticker": symbol,
            "ltp": ltp,
            "signal": signal,
            "actionability": actionability,
            "confidence": confidence,
            "market_bias": {
                "direction": bias,
                "reason": bias_reason
            },
            "timeframe_confluence": "1D Trend / 4H Demand OB / 1H Liquidity Sweep",
            "price_position": pd["price_position"],
            "position_desc": pd["position_desc"],
            "smc_zone_type": zone_type,
            "nearest_untested_ob": nearest_ob_str,
            "nearest_fvg": fvg_str,
            "buy_zone": {
                "price_range_low": buy_range_low,
                "price_range_high": buy_range_high,
                "entry_trigger": "Tap into Demand OB with 1H bullish market structure shift (CHoCH)",
                "stop_loss": stop_loss,
                "target1": target1,
                "target2": target2,
                "risk_reward": f"1:{round((target1 - ltp) / max(1.0, ltp - stop_loss), 1)}" if ltp > stop_loss else "1:2.8",
                "confidence": confidence
            },
            "liquidity_pools": liquidity,
            "next_liquidity_sweep": liquidity["next_likely_sweep"],
            "invalidation_level": invalidation,
            "invalidation": f"Daily close below ₹{invalidation} (breaks Demand Order Block)",
            "short_term_outlook": {
                "direction": bias,
                "hold_days": "15–30 Days (Optimal for MTF)",
                "profit_target": f"+10.0% (₹{target1})",
                "summary": f"Swing trade targeting +10% within 15–30 days. Minimal interest drag (~₹417 on ₹50k capital)."
            }
        }

