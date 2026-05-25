# Indian Trading Alerts (Beginner MVP)

A simple, beginner-friendly stock alert app for **Indian markets (Nifty 50)**.
Helps you find candidate trades using two proven, codeable strategies — without
having to pick stocks yourself.

> **Disclaimer:** This is an educational tool. It is **not** financial advice.
> Always do your own research, use stop-losses, and never trade with money you
> can't afford to lose. SEBI data shows ~90% of retail F&O traders lose money —
> stick to **delivery / cash equity** as a beginner.

---

## What it does

1. **Scans all 50 Nifty 50 stocks** automatically — you don't pick.
2. Applies **8 strategies inspired by legendary traders**:

   | Strategy | Inspired by | Type | Looks for |
   |---|---|---|---|
   | **Minervini-Lite** | Mark Minervini | Trend | Price above 50/150/200 SMAs, stacked correctly, 200-SMA rising |
   | **Kotegawa 25-day** | Takashi Kotegawa (BNF) | Mean reversion (light) | Price ≥ 5% below 25-SMA + RSI < 30, in long-term uptrend |
   | **BNF Classic** | Takashi Kotegawa (authentic) | Mean reversion (strict) | Price ≥ 15% below 25-SMA on a fresh selloff in a liquid large-cap |
   | **Darvas Box** | Nicolas Darvas | Breakout | New 52-week high after 20 days in a tight (≤ 8%) box |
   | **Turtle 20-day** | Richard Dennis (Turtles) | Breakout | Close > prior 20-day high, in confirmed uptrend; 2× ATR stop |
   | **Livermore Pivot** | Jesse Livermore | Breakout | Break above prior 60-day pivot high on ≥ 1.5× volume |
   | **Zanger Volume** | Dan Zanger | Breakout | Momentum leader (+30% YoY) breaks tight 2-month base on 2× volume |
   | **Episodic Pivot** | Kristjan Kullamägi (Qullamaggie) | Catalyst | After +20% in 3 months: 4%+ gap-up that holds, on 2× volume |

3. Shows you **only a handful of candidates per day** (no overwhelm).
4. Gives a **plain-English reason** (with stop-loss suggestions) for every alert.
5. Lets you **log paper trades** to practice without real money.

> **Tip:** Different strategies fire in different market conditions. **Trend** and **Breakout** strategies (Minervini, Darvas, Turtle, Livermore, Zanger, Qullamaggie) tend to fire in healthy bull markets. **Mean reversion** (Kotegawa) tends to fire after sharp selloffs. Don't be surprised if a scan returns zero candidates — the best traders sit out most days.

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

1. Click **"Scan Nifty 50"** — wait ~30s while it pulls data.
2. Review the candidates and the reason for each.
3. Click **"Paper Buy"** on any candidate to log a practice trade.
4. Track your paper trades on the **Trades** tab.

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
├── reports/                 Daily scan reports (auto-created, gitignored)
├── app/
│   ├── __init__.py
│   ├── main.py              FastAPI web app + routes + lifespan-managed scheduler
│   ├── scheduler.py         APScheduler that runs the daily scan
│   ├── reports.py           Report generation + Markdown rendering
│   ├── telegram_bot.py      Telegram bot (Phase 2)
│   ├── universe.py          Nifty 50 tickers
│   ├── data.py              yfinance data fetcher
│   ├── strategies.py        All 8 trader strategies
│   └── paper_trades.py      JSON-backed paper trade log
└── templates/
    └── index.html           Dashboard UI (Scanner / Reports / Trades tabs)
```

---

## Roadmap (next steps)

- [x] **Phase 1** - Web dashboard + paper trading
- [x] **Phase 2** - Telegram bot with inline approval buttons
- [x] **Phase 2.5** - Background scheduler runs all 8 strategies daily; saved reports
- [ ] **Phase 3** - Real order placement via Zerodha Kite Connect (see below)
- [ ] More strategies: VWAP bounce, Stan Weinstein Stage 2, Linda Raschke "Holy Grail"
- [ ] Backtest engine

---

## Background Scheduler &amp; Daily Reports

The app runs all 8 strategies automatically on a schedule and saves a report
each time. You can review past reports any day, see which strategies fired,
and click any candidate to paper-buy.

### Default schedule

- **When:** Weekdays at **16:00 IST** (30 minutes after NSE close at 15:30).
- **What it does:** Pulls 1 year of OHLCV for each Nifty 50 ticker, runs all 8
  strategies, ranks signals by score, and saves the result.
- **Where reports go:** `reports/&lt;scan_id&gt;.json` and `reports/&lt;scan_id&gt;.md`
  next to the project root. (Both files are gitignored.)

### Configure the schedule

Set these in your `.env` file:

```bash
SCAN_SCHEDULE_HOUR=16        # 0-23
SCAN_SCHEDULE_MINUTE=0       # 0-59
SCAN_SCHEDULE_DAYS=mon-fri   # APScheduler cron day_of_week
RUN_SCAN_ON_STARTUP=false    # set to 'true' to scan immediately on app start
```

### Manual control

In the **Reports** tab of the dashboard you can:

- See **next scheduled run** and **last actual run** at the top.
- Click **Run scan now &amp; save report** to trigger a scan immediately.
- Click any past report to expand: top picks, per-strategy hits, plain-English
  reasons, and Paper Buy buttons.

### API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/scheduler/status`     | Next/last run, whether a scan is in progress |
| `POST` | `/api/scan/run-now`         | Trigger a background scan now; returns the saved report |
| `GET`  | `/api/reports?limit=30`     | List recent report summaries |
| `GET`  | `/api/reports/{scan_id}`    | Fetch one full report |
| `GET`  | `/api/scan`                 | One-off scan returning signals (does NOT save a report) |

### Important

The scheduler runs **inside the FastAPI process**. So for the daily scan to
fire, the server must be up at the scheduled time. Easy hosting options:

- A small always-on VM (Oracle Free Tier, AWS t4g.nano, Hetzner CX11, etc).
- A free-tier container (Render, Fly.io) with a keep-alive ping.
- A home Raspberry Pi that runs `uvicorn` on boot.

If you'd rather not host anything, you can use **GitHub Actions cron** to call
`POST /api/scan/run-now` against a deployed app, or run `python -m app.scheduler`
on a cron job locally. (Tell me if you want either of these wired in.)

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

- `/scan` — scan Nifty 50; you'll get one message per candidate with inline buttons:
  - ✅ **Paper Buy 10** — logs a paper trade
  - ❌ **Skip** — dismisses
  - 📊 **Chart** — opens the stock on TradingView
  - 💼 **View on Kite** — opens the stock on Kite Web (you'll need to log in)
- `/trades` — list your recent paper trades

You can run the **web dashboard and the Telegram bot at the same time** — both
share the same `paper_trades.json` file.

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
