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
from typing import Any

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from app import paper_trades, scan_history
from app.data import fetch_benchmark, fetch_history, next_earnings_days_away
from app.morning_brief import fetch_morning_brief
from app.strategies import ALL_STRATEGIES, Signal
from app.universe import display_name, get_universe, list_universes

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("telegram_bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
PAPER_BUY_QTY = int(os.getenv("PAPER_BUY_QTY", "10"))
DEFAULT_UNIVERSE = os.getenv("DEFAULT_UNIVERSE", "NIFTY_50").upper()

WELCOME = (
    "👋 *Welcome to your Indian Trading Alerts bot.*\n\n"
    "I scan Indian equities using three beginner strategies:\n"
    "  • *Trend (Minervini-Lite)* — long-term uptrends with volume + RS\n"
    "  • *Mean Reversion (Kotegawa)* — oversold dips inside uptrends\n"
    "  • *Breakout (Darvas)* — fresh 52-week highs from tight bases\n\n"
    "*Commands:*\n"
    "/scan [universe] — scan a universe (default NIFTY\\_50)\n"
    "    Available: NIFTY\\_50, NIFTY\\_NEXT\\_50, NIFTY\\_100, FNO\\_LIQUID\n"
    "/universes — list available universes\n"
    "/brief — premarket macro snapshot (VIX, INR, Brent, global)\n"
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

def _scan_one(ticker: str, benchmark_df) -> list[Signal]:
    df = fetch_history(ticker, period="1y")
    if df is None:
        return []
    earn_days = next_earnings_days_away(ticker)
    out = []
    for fn in ALL_STRATEGIES.values():
        sig = fn(ticker, df, benchmark_df=benchmark_df, earnings_days_away=earn_days)
        if sig is not None:
            out.append(sig)
    return out


async def _scan_universe(universe_name: str) -> list[Signal]:
    tickers = get_universe(universe_name)
    benchmark_df = fetch_benchmark(period="1y")
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = await asyncio.gather(
            *[loop.run_in_executor(pool, _scan_one, t, benchmark_df) for t in tickers]
        )
    flat = [s for batch in results for s in batch]
    flat.sort(key=lambda s: s.score, reverse=True)
    return flat


# ---------- formatting ----------

STRATEGY_LABELS = {
    "minervini_lite": "📈 Trend (Minervini-Lite)",
    "kotegawa_meanrev": "🔄 Mean Reversion (Kotegawa)",
    "darvas_breakout": "🚀 Breakout (Darvas)",
}


def _signal_text(sig: Signal) -> str:
    name = display_name(sig.ticker)
    label = STRATEGY_LABELS.get(sig.strategy, sig.strategy)
    warn_str = ""
    if sig.warnings:
        warn_str = "\n\n⚠️ " + "\n⚠️ ".join(sig.warnings)
    return (
        f"*{name}* — ₹{sig.price:.2f}\n"
        f"_{label}_\n\n"
        f"{sig.reason}{warn_str}"
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


async def cmd_universes(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text("Not authorized.")
        return
    lines = ["*Available Universes*"]
    for u in list_universes():
        lines.append(f"  • `{u['name']}` — {u['size']} stocks")
    lines.append("\nUsage: `/scan NIFTY_100`")
    await update.message.reply_markdown("\n".join(lines))


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text("Not authorized.")
        return

    # Parse optional universe argument: /scan NIFTY_100
    universe = DEFAULT_UNIVERSE
    if ctx.args:
        universe = ctx.args[0].upper()

    tickers = get_universe(universe)
    if universe not in {u["name"] for u in list_universes()}:
        await update.message.reply_markdown(
            f"Unknown universe `{universe}`. Try /universes to see options. "
            f"Falling back to NIFTY\\_50."
        )
        universe = "NIFTY_50"
        tickers = get_universe(universe)

    await update.message.reply_text(
        f"🔍 Scanning {universe} ({len(tickers)} stocks)... "
        f"this can take 30-90s for larger universes."
    )
    signals = await _scan_universe(universe)

    # Persist for later review
    scan_history.record_scan(universe, [
        {**{
            "ticker": s.ticker,
            "strategy": s.strategy,
            "action": s.action,
            "price": s.price,
            "score": s.score,
            "reason": s.reason,
            "warnings": s.warnings,
            "display": display_name(s.ticker),
        }} for s in signals
    ])

    if not signals:
        await update.message.reply_text(
            "No candidates today. That's OK — the best traders sit out most days."
        )
        return
    await update.message.reply_text(f"Found {len(signals)} candidate(s):")
    for sig in signals:
        await update.message.reply_markdown(_signal_text(sig), reply_markup=_signal_buttons(sig))


async def cmd_brief(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text("Not authorized.")
        return
    await update.message.reply_text("📡 Fetching premarket snapshot...")
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, fetch_morning_brief)
    interp = data.get("interpretation", {})

    def _row(item: dict[str, Any]) -> str:
        price = item.get("price")
        chg = item.get("change_pct")
        price_s = f"{price:,.2f}" if isinstance(price, (int, float)) else "—"
        if chg is None:
            chg_s = "—"
        else:
            sign = "+" if chg >= 0 else ""
            chg_s = f"{sign}{chg:.2f}%"
        return f"  • {item['label']}: `{price_s}` ({chg_s})"

    lines = ["*🌅 Morning Brief*", "", "*India*"]
    lines += [_row(it) for it in data.get("india", [])]
    lines.append("\n*Commodities*")
    lines += [_row(it) for it in data.get("commodities", [])]
    lines.append("\n*Global*")
    lines += [_row(it) for it in data.get("global", [])]
    lines += [
        "",
        "*Reading the tape:*",
        f"  • India VIX: {interp.get('vix', '—')}",
        f"  • USD/INR: {interp.get('inr', '—')}",
        f"  • Brent: {interp.get('brent', '—')}",
    ]
    await update.message.reply_markdown("\n".join(lines))


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
    app.add_handler(CommandHandler("universes", cmd_universes))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(CommandHandler("trades", cmd_trades))
    app.add_handler(CallbackQueryHandler(cb_button))
    log.info("Bot starting (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
