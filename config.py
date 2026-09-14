"""
Configuration module for the Top 50 MTF Trading System.
Handles Dhan HQ API credentials, MTF interest rates, margin rules, and trade targets.
"""

import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env if present
env_file = BASE_DIR / ".env"
if env_file.exists():
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

# Dhan HQ API Configuration
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "1103250505")
DHAN_ACCESS_TOKEN = os.getenv(
    "DHAN_ACCESS_TOKEN",
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJ1c2VyUmVnaW9uIjoiUjEiLCJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzg5NDM4ODU1LCJpYXQiOjE3ODkzNTI0NTUsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTAzMjUwNTA1In0.9uM60mL_JZxg8jI9sjba4G2DPooUEWv7-D3EYokHwVvrvLE8rfdsOHI5cAz10tbOl1bzNnvsm8wC17mwOf0SFA"
)
DHAN_BASE_URL = os.getenv("DHAN_BASE_URL", "https://api.dhan.co/v2")

# MTF (Margin Trading Facility) Risk Parameters
# Default: 10.0% per annum (e.g. ₹5,000/yr on ₹50,000 capital)
MTF_ANNUAL_INTEREST_RATE = float(os.getenv("MTF_ANNUAL_INTEREST_RATE", "0.10"))  # 10% p.a.
MTF_DAILY_INTEREST_RATE = MTF_ANNUAL_INTEREST_RATE / 365.0

# Default leverage for Nifty 50 stocks (typically 25% margin = 4.0x leverage)
MTF_DEFAULT_LEVERAGE = float(os.getenv("MTF_DEFAULT_LEVERAGE", "4.0"))
MTF_DEFAULT_MARGIN_PCT = 1.0 / MTF_DEFAULT_LEVERAGE  # 0.25 (25%)

# Maintenance margin required by broker RMS before issuing margin call / auto-liquidation
# If collateral equity drops below this ratio of position value (typically 15% for Nifty 50), broker liquidates
MTF_MAINTENANCE_MARGIN_PCT = float(os.getenv("MTF_MAINTENANCE_MARGIN_PCT", "0.15"))  # 15%

# Trading Target & Stop Loss Rules
PROFIT_TARGET_PCT = float(os.getenv("PROFIT_TARGET_PCT", "0.10"))  # 10.0%
MAX_STOP_LOSS_PCT = float(os.getenv("MAX_STOP_LOSS_PCT", "0.035"))  # 3.5%
MIN_RISK_REWARD_RATIO = float(os.getenv("MIN_RISK_REWARD_RATIO", "2.5"))  # Target / SL >= 2.5

# Statutory and brokerage charges estimate (STT 0.1% buy + 0.1% sell, GST, Stamp duty, turnover fee)
ESTIMATED_STATUTORY_PCT = float(os.getenv("ESTIMATED_STATUTORY_PCT", "0.0025"))  # ~0.25% of turnover

# Web Dashboard Port & Host (supports cloud deployment PORT variable)
DASHBOARD_PORT = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "5050")))
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0" if os.getenv("PORT") else "127.0.0.1")


def update_access_token(new_token: str, client_id: str = None) -> bool:
    """Updates the .env file with a newly generated Dhan access token."""
    new_token = new_token.strip()
    if not new_token:
        return False
    
    global DHAN_ACCESS_TOKEN, DHAN_CLIENT_ID
    DHAN_ACCESS_TOKEN = new_token
    os.environ["DHAN_ACCESS_TOKEN"] = new_token
    
    if client_id:
        client_id = client_id.strip()
        DHAN_CLIENT_ID = client_id
        os.environ["DHAN_CLIENT_ID"] = client_id

    lines = []
    found_token = False
    found_client = False
    
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                if line.startswith("DHAN_ACCESS_TOKEN="):
                    lines.append(f"DHAN_ACCESS_TOKEN={new_token}\n")
                    found_token = True
                elif client_id and line.startswith("DHAN_CLIENT_ID="):
                    lines.append(f"DHAN_CLIENT_ID={client_id}\n")
                    found_client = True
                else:
                    lines.append(line)
    
    if not found_token:
        lines.append(f"DHAN_ACCESS_TOKEN={new_token}\n")
    if client_id and not found_client:
        lines.append(f"DHAN_CLIENT_ID={client_id}\n")

    with open(env_file, "w") as f:
        f.writelines(lines)

    return True
