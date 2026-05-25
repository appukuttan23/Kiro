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
2. Applies two well-known strategies:
   - **Minervini-Lite Trend Template** (momentum / trend-following)
     - Price > 50-day, 150-day, 200-day SMA
     - 50 SMA > 150 SMA > 200 SMA
     - 200 SMA trending up
   - **Kotegawa 25-day Mean Reversion** (buy-the-dip)
     - Price > 5% below 25-day SMA
     - RSI(14) < 30
3. Shows you **only a handful of candidates per day** (no overwhelm).
4. Gives a **plain-English reason** for every alert.
5. Lets you **log paper trades** to practice without real money.

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
├── app/
│   ├── __init__.py
│   ├── main.py              FastAPI web app + routes
│   ├── telegram_bot.py      Telegram bot (Phase 2)
│   ├── universe.py          Nifty 50 tickers
│   ├── data.py              yfinance data fetcher
│   ├── strategies.py        Minervini-lite + Kotegawa
│   └── paper_trades.py      JSON-backed paper trade log
└── templates/
    └── index.html           Dashboard UI
```

---

## Roadmap (next steps)

- [x] **Phase 1** — Web dashboard + paper trading
- [x] **Phase 2** — Telegram bot with inline approval buttons
- [ ] **Phase 3** — Real order placement via Zerodha Kite Connect (see below)
- [ ] Daily auto-scan via cron / GitHub Actions
- [ ] More strategies: Darvas Box, VWAP bounce
- [ ] Backtest engine

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
