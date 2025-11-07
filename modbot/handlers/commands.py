from __future__ import annotations

from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID, WELCOME_MESSAGE, HELP_MESSAGE, STATS_MESSAGE
from vouch_db import get_vouch_stats, search_vouches, format_vouch_for_display
from modbot.services.metrics import stats, roll_24h_if_needed
from modbot.services.vouches import submit_vouch_via_command


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_MESSAGE, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_MESSAGE, parse_mode="Markdown")


async def mystats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This command will be filled by strikes service in messages handler via reply
    from modbot.services.strikes import get_user_status

    user_id = update.effective_user.id
    user_status = get_user_status(user_id)

    if user_status["strikes"] == 0:
        await update.message.reply_text(
            "✓ Your Status: Clean Record\n\nYou have no active violations. Keep it up!",
            parse_mode="Markdown",
        )
        return

    recent = "\n".join([
        f"• {v.reason} (Severity: {v.severity})" for v in user_status["violations"][-5:]
    ])

    last_violation = user_status["last_violation"].strftime("%Y-%m-%d %H:%M") if user_status["last_violation"] else "N/A"
    text = (
        "🛡️ Your Moderation Status\n\n"
        f"Strikes: {user_status['strikes']}/{user_status['max_strikes']}\n"
        f"Last Violation: {last_violation}\n"
        f"Recent Violations:\n{recent}\n\n"
        f"Strikes reset after {user_status['reset_hours']} hours without violations."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ This command is only available to admins.")
        return

    roll_24h_if_needed()

    top_violations = []
    for vtype, count in sorted(stats["violations"].items(), key=lambda x: x[1], reverse=True)[:5]:
        top_violations.append(f"  • {vtype}: {count}")
    top_violations_str = "\n".join(top_violations) if top_violations else "  None yet"

    severity_breakdown = (
        "\n".join([f"  • {sev.capitalize()}: {cnt}" for sev, cnt in sorted(stats["severity_counts"].items(), key=lambda x: x[1], reverse=True)])
        if stats["severity_counts"] else "  None yet"
    )

    text = STATS_MESSAGE.format(
        total_removed=stats["total_removed"],
        last_24h=stats["last_24h"],
        vouches_sanitized=stats["vouches_sanitized"],
        top_violations=top_violations_str,
        group_count=len(stats["groups"]),
        users_warned=stats["users_warned"],
        users_muted=stats["users_muted"],
        severity_breakdown=severity_breakdown,
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def vouches_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        s = get_vouch_stats(chat_id=update.effective_chat.id)
        stats_text = (
            "📊 Vouch Statistics\n\n"
            f"Total Vouches: {s['total']}\n"
            f"Positive: {s['positive']} ✓\n"
            f"Negative: {s['negative']} ✗\n"
            f"Sanitized: {s['sanitized']} 🧹\n"
            f"Last 24h: {s['recent_24h']}\n\n"
            "Use `/vouches @username` to search for specific user vouches."
        )
        await update.message.reply_text(stats_text, parse_mode="Markdown")
        return

    query = " ".join(args)
    vouches = search_vouches(query, chat_id=update.effective_chat.id, limit=15)
    if not vouches:
        await update.message.reply_text(f"No vouches found for: {query}")
        return

    results = [format_vouch_for_display(v) for v in vouches]
    txt = f"**Vouches for: {query}**\n\n" + "\n".join(results)
    if len(vouches) == 15:
        txt += "\n\n_Showing first 15 results_"
    await update.message.reply_text(txt, parse_mode="Markdown")


async def vouch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _run_vouch_command(update, context, polarity="pos")


async def neg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _run_vouch_command(update, context, polarity="neg")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ask @username (optional note)")
        return

    target = " ".join(context.args)
    question = f"Is {target} vouched?"
    try:
        await context.bot.send_poll(
            chat_id=update.effective_chat.id,
            question=question[:290],
            options=["Yes", "No", "Unsure"],
            is_anonymous=False,
            allows_multiple_answers=False,
        )
    except Exception:
        await update.message.reply_text("Couldn't create the poll right now. Try again shortly.")


async def _run_vouch_command(update: Update, context: ContextTypes.DEFAULT_TYPE, polarity: str):
    args_text = " ".join(context.args) if context.args else ""
    success, message = await submit_vouch_via_command(
        chat=update.effective_chat,
        user=update.effective_user,
        args_text=args_text,
        polarity=polarity,
    )
    await update.message.reply_text(message, parse_mode="Markdown" if success else None)
