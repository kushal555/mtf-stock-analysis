"""
MTF (Margin Trading Facility) Risk & Profit Engine.
Calculates financing leverage, daily interest accrual, holding period decay schedules,
net profit after interest & charges, and the exact broker auto-liquidation trigger price.
"""

from typing import Dict, List, Optional
from config import (
    MTF_ANNUAL_INTEREST_RATE,
    MTF_DAILY_INTEREST_RATE,
    MTF_DEFAULT_LEVERAGE,
    MTF_MAINTENANCE_MARGIN_PCT,
    PROFIT_TARGET_PCT,
    ESTIMATED_STATUTORY_PCT
)


class MTFRiskEngine:
    @classmethod
    def calculate_trade_plan(
        cls,
        entry_price: float,
        capital: float = 50000.0,
        margin_pct: float = 0.25,
        target_pct: float = PROFIT_TARGET_PCT,
        stop_loss_price: Optional[float] = None,
        maintenance_margin_pct: float = MTF_MAINTENANCE_MARGIN_PCT,
        annual_interest_rate: float = MTF_ANNUAL_INTEREST_RATE
    ) -> Dict:
        """
        Calculates a complete MTF Trade Plan with interest decay, net profit across durations,
        and broker auto-square off liquidation thresholds.

        Parameters:
            entry_price: Entry stock price (₹)
            capital: User's own cash margin to deploy (₹)
            margin_pct: Margin required by broker (e.g., 0.25 = 25% margin = 4x leverage)
            target_pct: Profit target percentage (default: 0.10 = 10%)
            stop_loss_price: Trader's technical stop-loss level
            maintenance_margin_pct: Broker's minimum maintenance margin threshold before auto-liquidation
            annual_interest_rate: Annual MTF interest rate (e.g., 0.16 = 16% p.a.)
        """
        if entry_price <= 0 or capital <= 0 or margin_pct <= 0:
            return {}

        leverage = round(1.0 / margin_pct, 2)
        total_trade_value = capital * leverage
        quantity = int(total_trade_value // entry_price)
        
        # Recalculate exact position value based on integer shares
        actual_position_value = round(quantity * entry_price, 2)
        invested_margin = round(actual_position_value * margin_pct, 2)
        borrowed_amount = round(actual_position_value - invested_margin, 2)

        # Target and Exit Levels
        target_price = round(entry_price * (1.0 + target_pct), 2)
        if not stop_loss_price:
            stop_loss_price = round(entry_price * 0.965, 2)  # Default 3.5% SL

        # Gross Profit at Target (+10%)
        gross_profit = round(quantity * (target_price - entry_price), 2)
        gross_roi_pct = round((gross_profit / invested_margin) * 100.0, 2)

        # Estimated Statutory Charges (STT, Stamp Duty, GST, Exchange fees)
        # Applied on total turnover (buy + sell)
        turnover = (quantity * entry_price) + (quantity * target_price)
        statutory_charges = round(turnover * ESTIMATED_STATUTORY_PCT, 2)

        # Daily MTF Interest
        daily_interest_rate = annual_interest_rate / 365.0
        daily_interest_cost = round(borrowed_amount * daily_interest_rate, 2)

        # Broker Auto-Liquidation Trigger Price
        # Formula: P_liq = Borrowed_Per_Share / (1 - Maintenance_Margin)
        borrowed_per_share = borrowed_amount / quantity if quantity > 0 else 0
        liquidation_price = round(borrowed_per_share / (1.0 - maintenance_margin_pct), 2)
        
        # Buffer between entry and liquidation
        liquidation_drop_pct = round(((entry_price - liquidation_price) / entry_price) * 100.0, 2)
        sl_drop_pct = round(((entry_price - stop_loss_price) / entry_price) * 100.0, 2)
        safety_cushion_pct = round(liquidation_drop_pct - sl_drop_pct, 2)

        # Holding Duration Schedule (Net Profit analysis across time)
        holding_periods = [7, 15, 21, 30, 45, 60]
        schedule = []
        for days in holding_periods:
            interest = round(daily_interest_cost * days, 2)
            net_profit = round(gross_profit - interest - statutory_charges, 2)
            net_roi_pct = round((net_profit / invested_margin) * 100.0, 2)
            interest_drag_pct = round((interest / gross_profit) * 100.0, 1) if gross_profit > 0 else 0
            
            schedule.append({
                "days": days,
                "interest_cost": interest,
                "statutory_charges": statutory_charges,
                "net_profit": net_profit,
                "net_roi_pct": net_roi_pct,
                "interest_drag_pct": interest_drag_pct,
                "recommendation": "Optimal" if days <= 21 else ("Acceptable" if days <= 45 else "Time Decay Warning")
            })

        # Max Recommended Holding Days (before interest eats >25% of gross profit)
        max_recommended_days = int((gross_profit * 0.25) // daily_interest_cost) if daily_interest_cost > 0 else 60

        # 1 Month vs 2 Months vs Full Year Milestone
        annual_borrowed_interest = round(borrowed_amount * annual_interest_rate, 2)
        int_1m = round(daily_interest_cost * 30, 2)
        net_1m = round(gross_profit - int_1m - statutory_charges, 2)
        save_1m = round(annual_borrowed_interest - int_1m, 2)
        
        int_2m = round(daily_interest_cost * 60, 2)
        net_2m = round(gross_profit - int_2m - statutory_charges, 2)
        save_2m = round(annual_borrowed_interest - int_2m, 2)

        milestone_1_to_2m = {
            "annual_interest_rate_pct": round(annual_interest_rate * 100.0, 1),
            "annual_interest_cost": annual_borrowed_interest,
            "one_month": {
                "days": 30,
                "interest_paid": int_1m,
                "net_profit": net_1m,
                "interest_saved": save_1m,
                "net_roi_pct": round((net_1m / invested_margin) * 100.0, 1),
                "profit_retained_pct": round((net_1m / gross_profit) * 100.0, 1) if gross_profit > 0 else 0
            },
            "two_months": {
                "days": 60,
                "interest_paid": int_2m,
                "net_profit": net_2m,
                "interest_saved": save_2m,
                "net_roi_pct": round((net_2m / invested_margin) * 100.0, 1),
                "profit_retained_pct": round((net_2m / gross_profit) * 100.0, 1) if gross_profit > 0 else 0
            },
            "full_year": {
                "days": 365,
                "interest_paid": annual_borrowed_interest,
                "net_profit": round(gross_profit - annual_borrowed_interest - statutory_charges, 2)
            }
        }

        return {
            "entry_price": entry_price,
            "target_price": target_price,
            "stop_loss_price": stop_loss_price,
            "invested_capital": capital,
            "invested_margin": invested_margin,
            "borrowed_amount": borrowed_amount,
            "leverage": leverage,
            "quantity": quantity,
            "position_value": actual_position_value,
            "gross_profit": gross_profit,
            "gross_roi_pct": gross_roi_pct,
            "daily_interest_cost": daily_interest_cost,
            "statutory_charges": statutory_charges,
            "liquidation_price": liquidation_price,
            "liquidation_drop_pct": liquidation_drop_pct,
            "sl_drop_pct": sl_drop_pct,
            "safety_cushion_pct": safety_cushion_pct,
            "is_sl_safe_from_liquidation": stop_loss_price > liquidation_price,
            "max_recommended_days": max_recommended_days,
            "milestone_1_to_2m": milestone_1_to_2m,
            "schedule": schedule
        }
