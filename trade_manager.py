"""
Trade Manager & Google Sheets Backup Engine for MTF Swing Trading.
Persists trades locally and synchronizes bidirectionally with Google Sheets.
When Render or any container restarts, trades are automatically restored from Google Sheets.
"""

import os
import json
import csv
import io
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from config import (
    BASE_DIR,
    MTF_ANNUAL_INTEREST_RATE,
    MTF_DEFAULT_LEVERAGE,
    PROFIT_TARGET_PCT,
    MAX_STOP_LOSS_PCT,
    ESTIMATED_STATUTORY_PCT
)
from instruments import get_stock_by_symbol, _ALL_UNIQUE_STOCKS

# Local storage files
TRADES_FILE = BASE_DIR / "trades.json"
GOOGLE_SHEET_CONFIG_FILE = BASE_DIR / "google_sheet_config.json"


class TradeManager:
    _trades: List[Dict[str, Any]] = []
    _initialized: bool = False
    _google_sheet_url: str = ""
    _last_sync_time: Optional[str] = None
    _last_sync_status: str = "Not Connected"
    _sync_error: Optional[str] = None

    @classmethod
    def get_google_sheet_url(cls) -> str:
        """Retrieves configured Google Sheet Webhook URL."""
        if cls._google_sheet_url:
            return cls._google_sheet_url
        
        # Check environment variable
        env_url = os.getenv("GOOGLE_SHEET_WEBHOOK_URL", os.getenv("GOOGLE_SHEET_URL", "")).strip()
        if env_url:
            cls._google_sheet_url = env_url
            return cls._google_sheet_url
        
        # Check config file
        if GOOGLE_SHEET_CONFIG_FILE.exists():
            try:
                with open(GOOGLE_SHEET_CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                    cls._google_sheet_url = cfg.get("webhook_url", "").strip()
            except Exception:
                pass
        
        return cls._google_sheet_url

    @classmethod
    def set_google_sheet_url(cls, url: str) -> bool:
        """Updates and persists the Google Sheet Webhook URL."""
        cls._google_sheet_url = url.strip()
        try:
            with open(GOOGLE_SHEET_CONFIG_FILE, "w") as f:
                json.dump({"webhook_url": cls._google_sheet_url, "updated_at": datetime.now().isoformat()}, f, indent=2)
            os.environ["GOOGLE_SHEET_WEBHOOK_URL"] = cls._google_sheet_url
            return True
        except Exception as e:
            cls._sync_error = str(e)
            return False

    @classmethod
    def initialize(cls):
        """
        Initializes the trade manager on app/server startup.
        1. Loads existing local trades.json if present.
        2. If Google Sheet is configured, auto-imports all trades from Google Sheet
           to restore any state wiped by a Render container restart.
        """
        if cls._initialized:
            return

        # 1. Load local cache
        cls._load_from_local_file()

        # 2. Auto-import from Google Sheet on fresh startup
        url = cls.get_google_sheet_url()
        if url:
            print(f"[TradeManager] 🔄 Render startup: Auto-importing trades from Google Sheet...")
            success, count, msg = cls.import_from_google_sheet()
            if success:
                print(f"[TradeManager] ✅ Restored {count} trades from Google Sheet successfully!")
                cls._last_sync_status = f"Connected ({count} trades synced)"
            else:
                print(f"[TradeManager] ⚠️ Could not reach Google Sheet on startup: {msg}")
                cls._last_sync_status = f"Offline ({msg})"
        else:
            cls._last_sync_status = "Google Sheet Not Configured"

        cls._initialized = True

    @classmethod
    def _load_from_local_file(cls):
        """Reads trades from local JSON file."""
        if TRADES_FILE.exists():
            try:
                with open(TRADES_FILE, "r", encoding="utf-8") as f:
                    cls._trades = json.load(f)
            except Exception as e:
                print(f"[TradeManager] Error loading {TRADES_FILE}: {e}")
                cls._trades = []
        else:
            cls._trades = []

    @classmethod
    def _save_to_local_file(cls):
        """Writes current trades to local JSON file."""
        try:
            with open(TRADES_FILE, "w", encoding="utf-8") as f:
                json.dump(cls._trades, f, indent=2)
        except Exception as e:
            print(f"[TradeManager] Error saving to {TRADES_FILE}: {e}")

    # --- Trade CRUD Operations ---

    @classmethod
    def get_trades(cls, refresh_live_ltp: bool = True) -> Dict[str, Any]:
        """
        Returns all open and completed trades with live P&L calculations
        and overall portfolio summary.
        """
        cls.initialize()

        if refresh_live_ltp:
            cls._update_open_positions_live_ltp()

        open_trades = [t for t in cls._trades if t.get("status") == "OPEN"]
        completed_trades = [t for t in cls._trades if t.get("status") == "COMPLETED"]

        # Sort completed by exit_date desc, open by entry_date desc
        completed_trades.sort(key=lambda x: x.get("exit_date", x.get("entry_date", "")), reverse=True)
        open_trades.sort(key=lambda x: x.get("entry_date", ""), reverse=True)

        summary = cls.calculate_summary(open_trades, completed_trades)

        return {
            "open_trades": open_trades,
            "completed_trades": completed_trades,
            "total_trades": len(cls._trades),
            "summary": summary,
            "google_sheet": {
                "configured": bool(cls.get_google_sheet_url()),
                "url": cls.get_google_sheet_url(),
                "status": cls._last_sync_status,
                "last_synced": cls._last_sync_time,
                "error": cls._sync_error
            }
        }

    @classmethod
    def create_trade(
        cls,
        symbol: str,
        entry_price: float,
        capital: float = 50000.0,
        leverage: float = MTF_DEFAULT_LEVERAGE,
        target_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        entry_date: Optional[str] = None,
        notes: str = "",
        status: str = "OPEN",
        exit_price: Optional[float] = None,
        exit_date: Optional[str] = None,
        exit_reason: Optional[str] = None,
        source: str = "MANUAL"
    ) -> Dict[str, Any]:
        """
        Creates a new trade (either OPEN or directly COMPLETED).
        Saves locally and immediately backs up to Google Sheet.
        """
        cls.initialize()

        symbol = symbol.strip().upper()
        stock = get_stock_by_symbol(symbol)
        name = stock["name"] if stock else symbol

        entry_price = float(entry_price)
        capital = float(capital)
        leverage = float(leverage) if leverage > 0 else MTF_DEFAULT_LEVERAGE
        
        margin_pct = 1.0 / leverage
        total_position_val = capital * leverage
        quantity = int(total_position_val // entry_price) if entry_price > 0 else 1
        quantity = max(1, quantity)
        actual_position_val = round(quantity * entry_price, 2)
        borrowed_amount = round(actual_position_val - capital, 2)

        if not target_price or target_price <= 0:
            target_price = round(entry_price * (1.0 + PROFIT_TARGET_PCT), 2)
        if not stop_loss or stop_loss <= 0:
            stop_loss = round(entry_price * (1.0 - MAX_STOP_LOSS_PCT), 2)

        today_str = date.today().isoformat()
        if not entry_date:
            entry_date = today_str

        # Generate unique ID
        trade_id = f"TRD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{symbol[:4]}"

        # Daily interest
        daily_interest = round(borrowed_amount * (MTF_ANNUAL_INTEREST_RATE / 365.0), 2)

        trade = {
            "id": trade_id,
            "symbol": symbol,
            "name": name,
            "type": "BUY",
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2) if exit_price is not None else None,
            "quantity": quantity,
            "capital": round(capital, 2),
            "position_value": actual_position_val,
            "borrowed_amount": max(0.0, borrowed_amount),
            "leverage": leverage,
            "target_price": round(target_price, 2),
            "stop_loss": round(stop_loss, 2),
            "entry_date": entry_date,
            "exit_date": exit_date,
            "status": status.upper(),
            "notes": notes,
            "exit_reason": exit_reason or "",
            "source": source,
            "daily_interest": daily_interest,
            "hold_days": 0,
            "gross_pnl": 0.0,
            "mtf_interest": 0.0,
            "statutory_charges": 0.0,
            "net_pnl": 0.0,
            "roi_pct": 0.0,
            "current_ltp": round(entry_price, 2),
            "backed_up_to_sheet": False,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        # If created directly as COMPLETED (e.g. logging a past trade)
        if status.upper() == "COMPLETED" and exit_price is not None:
            cls._calculate_completed_pnl(trade, exit_price, exit_date or today_str, exit_reason or "MANUAL_EXIT")

        cls._trades.append(trade)
        cls._save_to_local_file()

        # Immediate backup to Google Sheet!
        sync_ok = cls.sync_single_trade_to_sheet(trade)
        trade["backed_up_to_sheet"] = sync_ok

        return trade

    @classmethod
    def complete_trade(
        cls,
        trade_id: str,
        exit_price: float,
        exit_date: Optional[str] = None,
        exit_reason: str = "TARGET_HIT",
        notes: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Marks an open trade as COMPLETED with exit price, computes net P&L
        including exact MTF interest accrued for the duration, and backs up to Google Sheet.
        """
        cls.initialize()

        trade = next((t for t in cls._trades if t["id"] == trade_id), None)
        if not trade:
            return None

        today_str = date.today().isoformat()
        exit_date = exit_date or today_str

        cls._calculate_completed_pnl(trade, float(exit_price), exit_date, exit_reason)
        if notes is not None:
            trade["notes"] = notes

        trade["updated_at"] = datetime.now().isoformat()
        cls._save_to_local_file()

        # Immediate backup to Google Sheet!
        sync_ok = cls.sync_single_trade_to_sheet(trade)
        trade["backed_up_to_sheet"] = sync_ok

        return trade

    @classmethod
    def delete_trade(cls, trade_id: str) -> bool:
        """Deletes a trade by ID and syncs change."""
        cls.initialize()
        initial_len = len(cls._trades)
        cls._trades = [t for t in cls._trades if t["id"] != trade_id]
        if len(cls._trades) < initial_len:
            cls._save_to_local_file()
            # If Google Sheet connected, perform bulk sync to update
            if cls.get_google_sheet_url():
                cls.sync_all_to_google_sheet()
            return True
        return False

    @classmethod
    def _calculate_completed_pnl(cls, trade: Dict[str, Any], exit_price: float, exit_date_str: str, exit_reason: str):
        """Calculates final realized P&L, hold duration, interest, and charges for a closed trade."""
        trade["exit_price"] = round(exit_price, 2)
        trade["exit_date"] = exit_date_str
        trade["exit_reason"] = exit_reason
        trade["status"] = "COMPLETED"

        # Calculate hold days
        try:
            d_entry = datetime.fromisoformat(trade["entry_date"]).date()
            d_exit = datetime.fromisoformat(exit_date_str).date()
            hold_days = max(1, (d_exit - d_entry).days)
        except Exception:
            hold_days = 1

        trade["hold_days"] = hold_days

        qty = trade["quantity"]
        entry_price = trade["entry_price"]
        capital = trade["capital"]
        borrowed = trade.get("borrowed_amount", 0.0)

        # Gross PnL
        gross_pnl = round(qty * (exit_price - entry_price), 2)
        trade["gross_pnl"] = gross_pnl

        # Accrued MTF Interest
        daily_interest_rate = MTF_ANNUAL_INTEREST_RATE / 365.0
        accrued_interest = round(borrowed * daily_interest_rate * hold_days, 2)
        trade["mtf_interest"] = accrued_interest

        # Statutory charges (0.25% of buy + sell turnover)
        turnover = (qty * entry_price) + (qty * exit_price)
        statutory = round(turnover * ESTIMATED_STATUTORY_PCT, 2)
        trade["statutory_charges"] = statutory

        # Net Profit in pocket
        net_pnl = round(gross_pnl - accrued_interest - statutory, 2)
        trade["net_pnl"] = net_pnl

        # Net ROI % on Margin Capital
        roi_pct = round((net_pnl / capital) * 100.0, 2) if capital > 0 else 0.0
        trade["roi_pct"] = roi_pct

    @classmethod
    def _update_open_positions_live_ltp(cls):
        """Updates live price and unrealized P&L for all open trades."""
        open_trades = [t for t in cls._trades if t.get("status") == "OPEN"]
        if not open_trades:
            return

        from dhan_client import DhanClient
        client = DhanClient()
        today = date.today()

        # Batch fetch LTP for all symbols in open trades
        sec_ids = []
        sym_to_trade = {}
        for t in open_trades:
            sym = t["symbol"]
            stock = get_stock_by_symbol(sym)
            if stock and "security_id" in stock:
                sid = int(stock["security_id"])
                sec_ids.append(sid)
                sym_to_trade[str(sid)] = t

        ltp_map = client.fetch_ltp_batch(sec_ids) if sec_ids else {}

        for sid_str, ltp in ltp_map.items():
            if sid_str in sym_to_trade:
                t = sym_to_trade[sid_str]
                t["current_ltp"] = round(ltp, 2)
                
                # Calculate days held so far
                try:
                    d_entry = datetime.fromisoformat(t["entry_date"]).date()
                    held_days = max(1, (today - d_entry).days)
                except Exception:
                    held_days = 1
                t["hold_days"] = held_days

                # Unrealized metrics
                qty = t["quantity"]
                entry_p = t["entry_price"]
                borrowed = t.get("borrowed_amount", 0.0)
                capital = t.get("capital", 1.0)

                gross = round(qty * (ltp - entry_p), 2)
                daily_rate = MTF_ANNUAL_INTEREST_RATE / 365.0
                interest = round(borrowed * daily_rate * held_days, 2)
                turnover = (qty * entry_p) + (qty * ltp)
                charges = round(turnover * ESTIMATED_STATUTORY_PCT, 2)

                net = round(gross - interest - charges, 2)
                roi = round((net / capital) * 100.0, 2) if capital > 0 else 0.0

                t["gross_pnl"] = gross
                t["mtf_interest"] = interest
                t["statutory_charges"] = charges
                t["net_pnl"] = net
                t["roi_pct"] = roi

                # Flag if target or SL is touched
                target = t.get("target_price", 0)
                sl = t.get("stop_loss", 0)
                if target and ltp >= target:
                    t["target_status"] = "TARGET_HIT_READY_TO_CLOSE"
                elif sl and ltp <= sl:
                    t["target_status"] = "STOP_LOSS_TRIGGERED"
                else:
                    t["target_status"] = "ACTIVE_IN_PROGRESS"

    @classmethod
    def calculate_summary(cls, open_trades: List[Dict], completed_trades: List[Dict]) -> Dict[str, Any]:
        """Calculates portfolio and performance summary metrics."""
        today_str = date.today().isoformat()

        today_completed = [t for t in completed_trades if t.get("exit_date") == today_str]
        today_net_pnl = round(sum(t.get("net_pnl", 0.0) for t in today_completed), 2)
        total_realized_pnl = round(sum(t.get("net_pnl", 0.0) for t in completed_trades), 2)

        total_open_unrealized_pnl = round(sum(t.get("net_pnl", 0.0) for t in open_trades), 2)
        total_active_capital = round(sum(t.get("capital", 0.0) for t in open_trades), 2)
        total_interest_accrued = round(
            sum(t.get("mtf_interest", 0.0) for t in completed_trades) +
            sum(t.get("mtf_interest", 0.0) for t in open_trades),
            2
        )

        wins = [t for t in completed_trades if t.get("net_pnl", 0.0) > 0]
        losses = [t for t in completed_trades if t.get("net_pnl", 0.0) <= 0]
        win_rate = round((len(wins) / len(completed_trades)) * 100.0, 1) if completed_trades else 0.0

        avg_roi = round(
            sum(t.get("roi_pct", 0.0) for t in completed_trades) / len(completed_trades), 1
        ) if completed_trades else 0.0

        return {
            "today_net_pnl": today_net_pnl,
            "today_trades_count": len(today_completed),
            "total_realized_pnl": total_realized_pnl,
            "total_unrealized_pnl": total_open_unrealized_pnl,
            "open_positions_count": len(open_trades),
            "completed_trades_count": len(completed_trades),
            "active_capital": total_active_capital,
            "total_interest_accrued": total_interest_accrued,
            "win_rate_pct": win_rate,
            "wins_count": len(wins),
            "losses_count": len(losses),
            "avg_roi_pct": avg_roi
        }

    # --- Google Sheets Synchronization & Auto-Import ---

    @classmethod
    def sync_single_trade_to_sheet(cls, trade: Dict[str, Any]) -> bool:
        """Pushes a single created or updated trade to Google Sheet."""
        url = cls.get_google_sheet_url()
        if not url:
            return False

        payload = {
            "action": "add_trade",
            "trade": cls._format_trade_for_sheet(trade)
        }
        success, res, err = cls._send_request(url, method="POST", payload=payload)
        if success:
            cls._last_sync_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cls._last_sync_status = "Connected & In Sync"
            cls._sync_error = None
            return True
        else:
            cls._sync_error = err
            cls._last_sync_status = f"Sync Warning: {err}"
            return False

    @classmethod
    def sync_all_to_google_sheet(cls) -> Tuple[bool, str]:
        """Performs a full bulk sync of all trades to Google Sheet."""
        url = cls.get_google_sheet_url()
        if not url:
            return False, "Google Sheet Webhook URL is not configured."

        formatted_trades = [cls._format_trade_for_sheet(t) for t in cls._trades]
        payload = {
            "action": "bulk_sync",
            "trades": formatted_trades
        }
        success, res, err = cls._send_request(url, method="POST", payload=payload)
        if success:
            cls._last_sync_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cls._last_sync_status = f"Connected ({len(cls._trades)} trades synced)"
            cls._sync_error = None
            for t in cls._trades:
                t["backed_up_to_sheet"] = True
            cls._save_to_local_file()
            return True, f"Successfully synchronized {len(cls._trades)} trades to Google Sheet."
        else:
            cls._sync_error = err
            cls._last_sync_status = f"Sync Error: {err}"
            return False, err

    @classmethod
    def import_from_google_sheet(cls) -> Tuple[bool, int, str]:
        """
        Auto-imports all trades from Google Sheet.
        Called on Render server start to restore wiped trade data.
        """
        url = cls.get_google_sheet_url()
        if not url:
            return False, 0, "No Google Sheet Webhook URL configured."

        # Fetch trades via GET or POST action=get_trades
        fetch_url = url + ("&action=get_trades" if "?" in url else "?action=get_trades")
        success, res, err = cls._send_request(fetch_url, method="GET")

        # If GET returned error, try POST with action: get_trades
        if not success:
            success, res, err = cls._send_request(url, method="POST", payload={"action": "get_trades"})

        if not success or not isinstance(res, dict):
            cls._sync_error = err
            return False, 0, err or "Failed to parse Google Sheet response."

        sheet_trades = res.get("trades", [])
        if not isinstance(sheet_trades, list):
            return False, 0, "Invalid trades format received from sheet."

        # Merge sheet trades into local store (preserving any newer local trades)
        existing_ids = {t["id"]: t for t in cls._trades}
        imported_count = 0

        for st in sheet_trades:
            tid = st.get("id")
            if not tid:
                continue
            if tid not in existing_ids:
                cls._trades.append(cls._normalize_sheet_trade(st))
                imported_count += 1
            else:
                # Merge if sheet has completion data that local was missing
                local = existing_ids[tid]
                if local.get("status") == "OPEN" and st.get("status") == "COMPLETED":
                    local.update(cls._normalize_sheet_trade(st))
                    imported_count += 1

        cls._save_to_local_file()
        cls._last_sync_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cls._last_sync_status = f"Connected ({len(cls._trades)} trades active)"
        cls._sync_error = None
        return True, len(cls._trades), f"Restored {imported_count} new trades ({len(cls._trades)} total)."

    @classmethod
    def _format_trade_for_sheet(cls, t: Dict[str, Any]) -> Dict[str, Any]:
        """Flattens trade dictionary for Google Sheet row mapping."""
        return {
            "id": t.get("id", ""),
            "date": t.get("entry_date", ""),
            "symbol": t.get("symbol", ""),
            "type": t.get("type", "BUY"),
            "entry_price": t.get("entry_price", 0.0),
            "exit_price": t.get("exit_price") if t.get("exit_price") is not None else "",
            "quantity": t.get("quantity", 0),
            "capital": t.get("capital", 0.0),
            "leverage": t.get("leverage", 4.0),
            "target_price": t.get("target_price", 0.0),
            "stop_loss": t.get("stop_loss", 0.0),
            "gross_pnl": t.get("gross_pnl", 0.0),
            "mtf_interest": t.get("mtf_interest", 0.0),
            "net_pnl": t.get("net_pnl", 0.0),
            "roi_pct": t.get("roi_pct", 0.0),
            "hold_days": t.get("hold_days", 0),
            "status": t.get("status", "OPEN"),
            "notes": t.get("notes", "") or t.get("exit_reason", "")
        }

    @classmethod
    def _normalize_sheet_trade(cls, st: Dict[str, Any]) -> Dict[str, Any]:
        """Converts trade format from Google Sheet back to full internal trade model."""
        entry_p = float(st.get("entry_price", 0.0))
        exit_p = float(st["exit_price"]) if st.get("exit_price") not in ("", None) else None
        qty = int(st.get("quantity", 1))
        cap = float(st.get("capital", entry_p * qty * 0.25))
        lev = float(st.get("leverage", 4.0))
        status = str(st.get("status", "OPEN")).upper()

        sym = str(st.get("symbol", "")).upper()
        stock = get_stock_by_symbol(sym)
        name = stock["name"] if stock else sym

        borrowed = max(0.0, round((qty * entry_p) - cap, 2))
        daily_interest = round(borrowed * (MTF_ANNUAL_INTEREST_RATE / 365.0), 2)

        return {
            "id": str(st.get("id", f"TRD-{int(time.time())}-{sym[:4]}")),
            "symbol": sym,
            "name": name,
            "type": str(st.get("type", "BUY")).upper(),
            "entry_price": entry_p,
            "exit_price": exit_p,
            "quantity": qty,
            "capital": cap,
            "position_value": round(qty * entry_p, 2),
            "borrowed_amount": borrowed,
            "leverage": lev,
            "target_price": float(st.get("target_price", entry_p * 1.10)),
            "stop_loss": float(st.get("stop_loss", entry_p * 0.965)),
            "entry_date": str(st.get("date", date.today().isoformat())),
            "exit_date": str(st.get("exit_date", "")) or (date.today().isoformat() if status == "COMPLETED" else None),
            "status": status,
            "notes": str(st.get("notes", "")),
            "exit_reason": str(st.get("notes", "RESTORED_FROM_SHEET")),
            "source": "GOOGLE_SHEET",
            "daily_interest": daily_interest,
            "hold_days": int(st.get("hold_days", 0)),
            "gross_pnl": float(st.get("gross_pnl", 0.0)),
            "mtf_interest": float(st.get("mtf_interest", 0.0)),
            "statutory_charges": 0.0,
            "net_pnl": float(st.get("net_pnl", 0.0)),
            "roi_pct": float(st.get("roi_pct", 0.0)),
            "current_ltp": entry_p if exit_p is None else exit_p,
            "backed_up_to_sheet": True,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

    # --- HTTP Redirect & Request Handler ---

    @classmethod
    def _send_request(
        cls,
        url: str,
        method: str = "GET",
        payload: Optional[Dict] = None,
        timeout: int = 8
    ) -> Tuple[bool, Any, str]:
        """
        Sends HTTP request to Google Apps Script with proper 302 redirect handling.
        Google Apps Script redirects all responses to script.googleusercontent.com.
        """
        if not url:
            return False, None, "URL is empty"

        try:
            req_data = json.dumps(payload).encode("utf-8") if payload is not None else None
            headers = {
                "Accept": "application/json",
                "User-Agent": "MTF-Trading-App/2.0"
            }
            if req_data:
                headers["Content-Type"] = "application/json"

            req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

            # Build opener with standard redirect handler (follows 302 to script.googleusercontent.com)
            opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
            with opener.open(req, timeout=timeout) as response:
                content = response.read().decode("utf-8")
                try:
                    parsed = json.loads(content)
                    return True, parsed, ""
                except json.JSONDecodeError:
                    return True, {"raw": content}, ""

        except urllib.error.HTTPError as e:
            return False, None, f"HTTP Error {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return False, None, f"Network Error: {e.reason}"
        except Exception as e:
            return False, None, f"Connection failed: {str(e)}"

    # --- CSV Export & Import ---

    @classmethod
    def export_csv(cls) -> str:
        """Exports all trades as CSV string."""
        cls.initialize()
        output = io.StringIO()
        fieldnames = [
            "id", "symbol", "name", "type", "entry_date", "entry_price",
            "exit_date", "exit_price", "quantity", "capital", "leverage",
            "target_price", "stop_loss", "hold_days", "gross_pnl",
            "mtf_interest", "net_pnl", "roi_pct", "status", "notes"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for t in cls._trades:
            writer.writerow(t)
        return output.getvalue()

    @classmethod
    def import_csv(cls, csv_text: str) -> Tuple[bool, int, str]:
        """Imports trades from CSV text."""
        cls.initialize()
        try:
            reader = csv.DictReader(io.StringIO(csv_text.strip()))
            count = 0
            existing_ids = {t["id"] for t in cls._trades}
            for row in reader:
                tid = row.get("id") or f"TRD-{int(time.time())}-{row.get('symbol', 'STK')}"
                if tid not in existing_ids:
                    row["id"] = tid
                    cls._trades.append(cls._normalize_sheet_trade(row))
                    count += 1
            cls._save_to_local_file()
            return True, count, f"Imported {count} trades successfully."
        except Exception as e:
            return False, 0, f"CSV Import error: {str(e)}"
