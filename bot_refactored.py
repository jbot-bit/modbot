"""
Telegram Moderation Bot - Refactored Entrypoint
Run with long polling by default, or webhook if configured.
"""
import logging
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

from config import (
    BOT_TOKEN,
    ADMIN_ID,
    GUIDE_MESSAGE,
    GUIDE_POST_INTERVAL_HOURS,
    GUIDE_DELETE_AFTER_SECONDS,
)
from modbot.logging import configure_logging
from modbot.handlers.commands import (
    start_command,
    help_command,
    stats_command,
    mystats_command,
    vouches_command,
    vouch_command,
    neg_command,
    ask_command,
)
from modbot.handlers.messages import handle_text_message
from modbot.services.metrics import stats


logger = configure_logging(logging.INFO)
GUIDE_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("➕ Vouch", callback_data="guide_cmd_vouch"),
        InlineKeyboardButton("⚠ Neg", callback_data="guide_cmd_neg"),
    ],
    [
        InlineKeyboardButton("❓ Ask", callback_data="guide_cmd_ask"),
        InlineKeyboardButton("📚 Lookup", callback_data="guide_cmd_lookup"),
    ],
    [
        InlineKeyboardButton("Keep it clean", callback_data="guide_rules"),
    ],
])


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")


async def send_usage_tip(context: ContextTypes.DEFAULT_TYPE):
    if not stats["groups"]:
        return

    for chat_id in list(stats["groups"]):
        try:
            sent = await context.bot.send_message(
                chat_id=chat_id,
                text=GUIDE_MESSAGE,
                parse_mode="Markdown",
                reply_markup=GUIDE_KEYBOARD,
            )
        except Exception as exc:
            logger.debug("Failed to broadcast guide to %s: %s", chat_id, exc)
            continue

        if context.job_queue:
            context.job_queue.run_once(
                delete_tip_message,
                when=GUIDE_DELETE_AFTER_SECONDS,
                data={"chat_id": chat_id, "message_id": sent.message_id},
            )


async def delete_tip_message(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    if not chat_id or not message_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def guide_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    responses = {
        "guide_cmd_vouch": "Type /vouch @user note to record a positive vouch.",
        "guide_cmd_neg": "Type /neg @user note for a warning or negative vouch.",
        "guide_cmd_ask": "Type /ask @user to post a poll asking if they’re vouched.",
        "guide_cmd_lookup": "Type /vouches @user to read their history.",
        "guide_rules": "Avoid explicit illegal wording so the bot doesn’t sanitize or delete your post.",
    }
    msg = responses.get(data, "Use the commands shown for vouching.")
    await query.answer(msg, show_alert=True)


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set in environment variables!")
        return
    if not ADMIN_ID or ADMIN_ID == 0:
        logger.error("ADMIN_ID not set in environment variables!")
        return

    run_mode = os.getenv("RUN_MODE", "polling").lower()
    port = int(os.getenv("PORT", "5000"))
    webhook_url = os.getenv("WEBHOOK_URL")

    logger.info("Starting Telegram Moderation Bot (%s mode)...", run_mode)

    application = Application.builder().token(BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("mystats", mystats_command))
    application.add_handler(CommandHandler("vouches", vouches_command))
    application.add_handler(CommandHandler("vouch", vouch_command))
    application.add_handler(CommandHandler("neg", neg_command))
    application.add_handler(CommandHandler("ask", ask_command))

    # Messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(CallbackQueryHandler(guide_callback, pattern="guide_.*"))

    # Errors
    application.add_error_handler(error_handler)

    # Scheduled reminders
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            send_usage_tip,
            interval=GUIDE_POST_INTERVAL_HOURS * 3600,
            first=600,
            name="usage_tip",
        )
    else:
        logger.warning("Job queue unavailable; usage-tip reminders disabled. Install python-telegram-bot[job-queue] to enable.")

    if run_mode == "webhook":
        if not webhook_url:
            logger.error("WEBHOOK_URL must be set for webhook mode")
            return
        logger.info("Running webhook at %s", webhook_url)
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="/webhook",
            webhook_url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Running in long polling mode")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
