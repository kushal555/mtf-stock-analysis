# Top 50 Stocks MTF Trading System

An automated technical analysis scanner and MTF (Margin Trading Facility) trade management platform tailored for the **Top 50 Indian Stocks (NIFTY 50)**.

Engineered specifically for positional swing traders targeting **~10% profit**, with built-in mathematical models to manage **MTF interest decay vs. profit ratios** and protect against **broker auto-liquidation (auto-square off)**.

---

## 🌟 Key Features

1. **Top 50 Nifty Universe**:
   - Pre-mapped with Dhan Security IDs, sectors, and MTF margin brackets (20% - 25% margin / 4x - 5x leverage).
2. **Actionable Buy & Sell Zones**:
   - **Buy Zone**: High-confluence accumulation band calculated from dynamic support (20 EMA, 50 SMA, 45-day swing lows).
   - **Sell Zone**: Primary target at **+10% profit** from entry.
   - **Safe Stop-Loss**: Strictly capped at 3.0% - 3.5% risk (giving a minimum **1 : 2.8+ Risk-to-Reward ratio**).
3. **MTF Interest vs. Profit Decay Engine**:
   - Models Dhan's daily MTF interest (~16% p.a. or 0.0438% per day) on borrowed funds.
   - Computes **Net In-Pocket Profit** and **Net ROI on Margin** after interest & statutory charges across 7, 15, 21, 30, 45, and 60 days.
   - Calculates the **Max Recommended Holding Period** before interest eats into profits.
4. **Broker Auto-Liquidation (RMS Square-Off) Prevention**:
   - Computes the exact **Broker Auto-Liquidation Trigger Price**:
     $$P_{\text{liquidation}} = \frac{\text{Borrowed Capital Per Share}}{1 - \text{Maintenance Margin \%}}$$
   - Guarantees your Stop-Loss sits **above** the broker's auto-square off price, so you exit on disciplined terms rather than suffering a broker market liquidation!
5. **Interactive Web Dashboard**:
   - Real-time watchlist table with status badges (`🟢 IN BUY ZONE`, `🟡 NEAR BUY ZONE`, `★ 10% TARGET`).
   - Interactive MTF simulator modal with sliders for Margin Capital, Leverage, and Days Held.
   - One-click Dhan Token update modal.
6. **Command-Line Scanner (CLI)**:
   - Fast terminal scanner with color-coded levels and single-stock drilldown.

---

## 🚀 Quick Start

### 1. Run the Terminal Scanner
To scan all 50 stocks:
```bash
python cli.py --scan
```

To filter only stocks currently inside or approaching the Buy Zone:
```bash
python cli.py --buy-zone
```

To get a complete MTF trade plan for a specific stock (e.g. RELIANCE, TCS, HDFCBANK):
```bash
python cli.py --stock RELIANCE --capital 50000
```

---

### 2. Launch the Web Dashboard
Start the local dashboard server:
```bash
python dashboard.py
```
Open your browser at:
👉 **[http://localhost:5050](http://localhost:5050)**

From the dashboard you can:
- View all 50 stocks with live prices, Buy Zones, 10% Targets, and Safe Stop-Loss levels.
- Click **"Simulate MTF"** on any stock to open interactive sliders and inspect the exact interest decay table and liquidation buffer.
- Click **"🔑 Update Dhan Token"** to paste a new 24-hour token when needed.

---

## 🔑 Dhan API Configuration

Your credentials are stored in `.env`:
```env
DHAN_CLIENT_ID=1103250505
DHAN_ACCESS_TOKEN=<your_jwt_token>
MTF_ANNUAL_INTEREST_RATE=0.16
MTF_MAINTENANCE_MARGIN_PCT=0.15
PROFIT_TARGET_PCT=0.10
MAX_STOP_LOSS_PCT=0.035
```

> [!NOTE]
> **Dhan Data APIs vs. Trading APIs**:
> - Dhan tokens expire every 24 hours.
> - On Dhan HQ developer console (`api.dhan.co`), ensure **Data APIs** are subscribed for live market feed access.
> - If Data APIs are not subscribed, the system automatically falls back to live free NSE market feeds, ensuring uninterrupted trading analysis!

---

## 🧪 Running Automated Tests
Run the test suite to verify MTF math, indicator formulas, and APIs:
```bash
python -m unittest test_suite.py
```
