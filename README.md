# Indian Trading Alerts (Beginner MVP)

A simple, beginner-friendly stock alert app for **Indian markets**.
Helps you find candidate trades using proven, codeable strategies — without
having to pick stocks yourself.

> **Disclaimer:** This is an educational tool. It is **not** financial advice.
> Always do your own research, use stop-losses, and never trade with money you
> can't afford to lose. SEBI data shows ~90% of retail F&O traders lose money —
> stick to **delivery / cash equity** as a beginner.

---

## What it does

1. **Scans configurable universes** automatically — you don't pick the stock.
   - `NIFTY_50` (50)
   - `NIFTY_NEXT_50` (50)
   - `NIFTY_100` (100)
   - `FNO_LIQUID` (~150 most-liquid F&O names)
2. Applies **three** well-known strategies:
   - **Minervini-Lite Trend Template** (momentum / trend-following)
     - Price > 50, 150, 200-day SMAs
     - 50 SMA > 150 SMA > 200 SMA
     - 200 SMA trending up
     - Within 25% of 52-week high
     - Recent 5d volume ≥ 1.2× of 20d baseline (institutional accumulation proxy)
     - **Bonus**: outperforming Nifty over 3 months (relative strength)
   - **Kotegawa 25-day Mean Reversion** (buy-the-dip)
     - Price ≥ 5% below 25-day SMA
     - RSI(14) < 30
     - Above 200-day SMA (uptrend filter)
     - **Filter**: not significantly underperforming Nifty over 6M (no falling knives)
   - **Darvas / 52-Week-High Breakout** (NEW — pattern-based momentum)
     - Today closes at fresh 252-day high
     - Prior 20-day range ≤ 15% (tight consolidation)
     - Today's volume ≥ 1.5× of 20-day average
     - Price > 50-day SMA
3. Shows you only a handful of candidates per day with a **plain-English reason**.
4. **Soft warnings**: if earnings fall within ~3 days, the candidate is flagged
   (not rejected — yfinance earnings dates are flaky).
5. **Morning Brief tab**: snapshot of Nifty spot, India VIX, USD/INR, Brent,
   Gold, S&P 500, Dow, Nasdaq, Nikkei, Hang Seng — with one-line interpretations.
6. **Scan history**: every scan is persisted so you can review signal quality
   over time and (later) backtest.
7. **Paper-trade log** to practise without real money.

---

## Quick Start

### 1. Prerequisites

- Python 3.10 or newer ([download here](https://www.python.org/downloads/))

### 2. Install

```bash
pip install -r requirements.txt
```

### 3. Run

```bash
uvicorn app.main:app --reload
```

Then open http://localhost:8000 in your browser.

### 4. Use it

1. The **Morning Brief** loads automatically — check VIX, INR, crude before you trade.
2. Switch to the **Scanner** tab, pick a universe, click **Scan**.
3. Review candidates and the reason for each.
4. Click **Paper Buy** to log a practice trade.
5. Track your paper trades on the **Paper Trades** tab.
6. Review your scan history on the **Scan History** tab.

---

## Recommended Daily Routine (for delivery / swing trading)

| Time (IST) | Step |
|---|---|
| **8:30 AM** | Open Morning Brief tab. Read VIX, INR, Brent, US close. |
| **8:45 AM** | Manually check GIFT Nifty pre-market on businesstoday.in or NDTV Profit. |
| **9:00 AM** | Manually check FII / DII data (released ~6 PM previous evening on NSE). |
| **9:15 AM** | Avoid the first 15 min — opening volatility kills tight stops. |
| **9:30 AM–3:30 PM** | If you are placing manual orders for prior day's signals, do it now. |
| **4:00 PM** | EOD data settles. |
| **4:30 PM** | Run **Scan NIFTY_100** (or **FNO_LIQUID** for wider net). |
| **4:35 PM** | Review top candidates, eyeball charts on TradingView. |
| **4:45 PM** | Log paper-buys for top 1–3 picks. Place real orders next morning at 9:20. |

---

## Position Sizing for ₹20,000 Capital

| Approach | Stocks | Per stock | Stop-loss per trade |
|---|---|---|---|
| Recommended | 4–5 | ₹4,000–5,000 | ₹400 (2% of capital) |

Never lose more than 2% of your total capital on a single trade.

---

## Project Layout

```
.
├── requirements.txt
├── README.md
├── .env.example             Template for Telegram bot config
├── app/
│   ├── __init__.py
│   ├── main.py              FastAPI web app + routes
│   ├── telegram_bot.py      Telegram bot (Phase 2)
│   ├── universe.py          NIFTY_50 / NIFTY_NEXT_50 / NIFTY_100 / FNO_LIQUID
│   ├── data.py              yfinance wrapper + benchmark + earnings lookup
│   ├── strategies.py        Minervini-lite + Kotegawa + Darvas
│   ├── morning_brief.py     Premarket macro snapshot
│   ├── scan_history.py      Persistent scan log
│   └── paper_trades.py      JSON-backed paper trade log
└── templates/
    └── index.html           Dashboard UI (4 tabs)
```

---

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/` | Web dashboard |
| `GET`  | `/api/universes` | List available universes |
| `GET`  | `/api/scan?universe=NIFTY_100` | Run a scan |
| `GET`  | `/api/morning-brief` | Premarket macro snapshot |
| `GET`  | `/api/scan-history?limit=25` | Recent scan records |
| `GET`  | `/api/trades` | List paper trades |
| `POST` | `/api/trades` | Log a paper trade |
| `POST` | `/api/trades/{id}/close` | Close an open paper trade |

---

## Roadmap

- [x] **Phase 1** — Web dashboard + paper trading
- [x] **Phase 2** — Telegram bot with inline approval buttons
- [x] **Scanner v2** — volume thrust, relative strength, Darvas breakout, expanded universe, morning brief, scan history
- [ ] **Phase 3** — Real order placement via Zerodha Kite Connect (see below)
- [ ] Daily auto-scan via cron / GitHub Actions
- [ ] Backtest engine that replays scan history against subsequent price action
- [ ] Sector / industry rollups (which sectors are leading?)
- [ ] FII / DII flow data (requires NSE bhavcopy integration)

---

## Telegram Bot Setup (Phase 2)

The bot pings you on your phone with each candidate and lets you approve/skip with a tap.

### 1. Create your bot

1. Open Telegram and message **@BotFather**.
2. Send `/newbot` and follow the prompts. Note the **bot token** it gives you.

### 2. Configure

```bash
cp .env.example .env
# Edit .env and paste your bot token into TELEGRAM_BOT_TOKEN
```

### 3. Run

```bash
python -m app.telegram_bot
```

In Telegram, find your bot and send `/start`. It will reply with your chat id —
paste that into `.env` as `TELEGRAM_ALLOWED_CHAT_ID` so only you can use the bot,
then restart it.

### 4. Use it

- `/scan [universe]` — scan a universe (default: `NIFTY_50`). Examples:
  - `/scan` — default
  - `/scan NIFTY_100`
  - `/scan FNO_LIQUID`
- `/universes` — list available universes
- `/brief` — premarket macro snapshot
- `/trades` — list your recent paper trades

Each candidate comes with inline buttons:
  - ✅ **Paper Buy 10** — logs a paper trade
  - ❌ **Skip** — dismisses
  - 📊 **Chart** — opens the stock on TradingView
  - 💼 **View on Kite** — opens the stock on Kite Web (login required)

You can run the **web dashboard and the Telegram bot at the same time** — both
share the same `paper_trades.json` and `scan_history.json` files.

---

## Phase 3: Real Order Placement (Important Read Before Enabling)

> ⚠️ **Real money is at stake. Phase 3 is intentionally NOT implemented yet.**
> Use the bot for paper trades for **at least 30 days** before enabling real orders.

### What it would take

To let the bot actually buy/sell on your Zerodha account, we'd need:

1. **A Kite Connect subscription** from Zerodha
   (~₹2,000 one-time + ₹2,000/month — see [kite.trade](https://kite.trade)).
2. Your **API key + API secret**.
3. A **daily login flow** (Zerodha requires a fresh access token each day via OAuth).
4. **Hardcoded safety caps** — values that the bot will *refuse* to exceed:
   - `MAX_TRADE_VALUE_INR` — e.g. ₹5,000 (so no single order exceeds 25% of a ₹20k account).
   - `MAX_DAILY_LOSS_INR` — e.g. ₹400 (kills the bot for the day if hit).
   - `MAX_OPEN_POSITIONS` — e.g. 5.
   - `ALLOWED_PRODUCT_TYPES` — limited to `CNC` (delivery) initially. **No F&O.**
5. A **two-tap confirmation flow** in Telegram, e.g.:
   ```
   Bot:  Place LIVE order? RELIANCE BUY 2 @ MARKET (~₹4,000)
         [ Confirm ]  [ Cancel ]
   You:  Confirm
   Bot:  Type "YES" to confirm again.
   You:  YES
   Bot:  Order placed. Order id 240118000001
   ```
6. **Market hours guard** — refuse orders outside 09:15–15:30 IST on trading days.
7. **Rate limiting** — max N orders per minute / hour.

### Why we're not doing this in the MVP

- A bug at this stage costs **real money**, not paper money.
- You want to trust the strategies first — track 20–30 paper trades and see if they actually win.
- SEBI guidelines for retail algo trading are evolving; subscribing to Kite Connect commits you to certain rules.
- A safer next step is **alerts → manual click on the "View on Kite" button → place the order yourself in Kite**. You retain full control and the bot still saves you the work of finding the trade.

### Suggested progression

| Stage | Duration | Capital at risk |
|---|---|---|
| Paper trade only (now) | 30+ days | ₹0 |
| Manual orders via "View on Kite" link | 30+ days | small (₹2–5k positions) |
| Phase 3: Auto orders with double-confirm + caps | After you trust it | up to your full account |

Once you're ready for Phase 3, open an issue or message and we'll wire it in
behind a feature flag.
