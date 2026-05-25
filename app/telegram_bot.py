"""Telegram bot for trading alerts.

Run with:
    python -m app.telegram_bot

Set TELEGRAM_BOT_TOKEN in .env (see .env.example).

Phase 2 (current): the bot sends scan candidates with inline buttons:
    - Paper Buy   -> logs to paper_trades.json
    - Chart       -> opens TradingView in your browser
    - View on Kite-> opens the stock's marketwatch page on Kite Web
    - Skip        -> dismisses

Phase 3 (future, see README): replace the "Paper Buy" handler with a real
Zerodha Kite Connect order placement, gated by hard risk caps and a
"Confirm twice" flow.
"""
from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from app import paper_trades
from app.data import fetch_history
from app.strategies import ALL_STRATEGIES, Signal
from app.universe import NIFTY_50, display_name

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("telegram_bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
PAPER_BUY_QTY = int(os.getenv("PAPER_BUY_QTY", "10"))

WELCOME = (
    "👋 *Welcome to your Indian Trading Alerts bot.*\n\n"
    "I scan Nifty 50 stocks using two beginner strategies:\n"
    "  • *Trend (Minervini-Lite)* — long-term uptrends\n"
    "  • *Mean Reversion (Kotegawa)* — oversold dips in uptrends\n\n"
    "*Commands:*\n"
    "/scan — scan Nifty 50 now\n"
    "/trades — show open paper trades\n"
    "/help — show this message\n\n"
    "_Educational tool only. Not financial advice._"
)


# ---------- access control ----------

def _allowed(update: Update) -> bool:
    if not ALLOWED_CHAT_ID:
        return True
    return str(update.effective_chat.id) == ALLOWED_CHAT_ID


# ---------- scan worker (blocking I/O off the event loop) ----------

def _scan_one(ticker: str) -> list[Signal]:
    df = fetch_history(ticker, period="1y")
    if df is None:
        return []
    out = []
    for fn in ALL_STRATEGIES.values():
        sig = fn(ticker, df)
        if sig is not None:
            out.append(sig)
    return out


async def _scan_universe() -> list[Signal]:
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = await asyncio.gather(
            *[loop.run_in_executor(pool, _scan_one, t) for t in NIFTY_50]
        )
    flat = [s for batch in results for s in batch]
    flat.sort(key=lambda s: s.score, reverse=True)
    return flat


# ---------- formatting ----------

STRATEGY_LABELS = {
    "minervini_lite": "📈 Trend (Minervini-Lite)",
    "kotegawa_meanrev": "🔄 Mean Reversion (Kotegawa)",
}


def _signal_text(sig: Signal) -> str:
    name = display_name(sig.ticker)
    label = STRATEGY_LABELS.get(sig.strategy, sig.strategy)
    return (
        f"*{name}* — ₹{sig.price:.2f}\n"
        f"_{label}_\n\n"
        f"{sig.reason}"
    )


def _signal_buttons(sig: Signal) -> InlineKeyboardMarkup:
    name = display_name(sig.ticker)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"✅ Paper Buy {PAPER_BUY_QTY}",
                    callback_data=f"buy|{sig.ticker}|{sig.price:.2f}|{sig.strategy}",
                ),
                InlineKeyboardButton("❌ Skip", callback_data=f"skip|{sig.ticker}"),
            ],
            [
                InlineKeyboardButton(
                    "📊 Chart",
                    url=f"https://www.tradingview.com/chart/?symbol=NSE%3A{name}",
                ),
                InlineKeyboardButton(
                    "💼 View on Kite",
                    url=f"https://kite.zerodha.com/chart/ext/tvc/NSE/{name}",
                ),
            ],
        ]
    )


# ---------- command handlers ----------

async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    log.info("/start from chat_id=%s", chat_id)
    extra = (
        f"\n\n_Your chat id is_ `{chat_id}`."
        " Set `TELEGRAM_ALLOWED_CHAT_ID` to this in `.env` to lock the bot to you."
    )
    await update.message.reply_markdown(WELCOME + extra)


async def cmd_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_markdown(WELCOME)


async def cmd_scan(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text("Not authorized.")
        return
    await update.message.reply_text(f"🔍 Scanning {len(NIFTY_50)} stocks... (~30s)")
    signals = await _scan_universe()
    if not signals:
        await update.message.reply_text(
            "No candidates today. That's OK — the best traders sit out most days."
        )
        return
    await update.message.reply_text(f"Found {len(signals)} candidate(s):")
    for sig in signals:
        await update.message.reply_markdown(_signal_text(sig), reply_markup=_signal_buttons(sig))


async def cmd_trades(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text("Not authorized.")
        return
    trades = paper_trades.list_trades()
    if not trades:
        await update.message.reply_text("No paper trades yet. Run /scan and approve a candidate.")
        return
    lines = ["*Paper Trades*\n"]
    for t in trades[-15:]:  # last 15
        name = display_name(t["ticker"])
        if t["status"] == "OPEN":
            lines.append(f"• `{t['id']}` *{name}* {t['action']} {t['qty']} @ ₹{t['price']} (OPEN)")
        else:
            pnl = t.get("pnl", 0)
            sign = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"• `{t['id']}` *{name}* CLOSED — {sign} ₹{pnl} ({t.get('pnl_pct', 0)}%)"
            )
    await update.message.reply_markdown("\n".join(lines))


# ---------- callback (button) handler ----------

async def cb_button(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not _allowed(update):
        return
    parts = (q.data or "").split("|")
    action = parts[0]

    if action == "skip":
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text("Skipped.")
        return

    if action == "buy" and len(parts) >= 4:
        ticker, price_s, strategy = parts[1], parts[2], parts[3]
        price = float(price_s)
        trade = paper_trades.add_trade(
            ticker=ticker,
            action="BUY",
            price=price,
            qty=PAPER_BUY_QTY,
            reason=f"Telegram approval ({strategy})",
        )
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_markdown(
            f"✅ Paper trade logged: *{display_name(ticker)}* "
            f"BUY {PAPER_BUY_QTY} @ ₹{price:.2f} "
            f"(value ₹{trade['value']}). Trade id `{trade['id']}`."
        )
        return


# ---------- entry point ----------

def main() -> None:
    if not TOKEN:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and add your token from @BotFather."
        )
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("trades", cmd_trades))
    app.add_handler(CallbackQueryHandler(cb_button))
    log.info("Bot starting (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
