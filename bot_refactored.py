"""
Telegram Moderation Bot - Refactored Entrypoint
Optimized for Replit deployment with webhook support.
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
    commands_command,
    help_callback,
    stats_command,
    mystats_command,
    search_command,
    ask_command,
    leaderboard_command,
    myvouches_command,
    sync_vouches_command,
    add_keyword,
    remove_keyword,
    list_keywords,
    deletevouch_command,
    debug_vouches,
    quick_reminder,
    handle_missed_vouches,
)
from modbot.handlers.messages import handle_text_message
from vouch_db import cleanup_old_vouch_retry_attempts
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
    """Log and handle errors gracefully without crashing the bot."""
    try:
        logger.error(f"Update {update} caused error {context.error}")
    except Exception as e:
        logger.error(f"Error handler failed: {e}")


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
        "guide_cmd_ask": "Type /ask @user to post a poll asking if they're vouched.",
        "guide_cmd_lookup": "Type /search @user to read their history.",
        "guide_rules": "Avoid explicit illegal wording so the bot doesn't sanitize or delete your post.",
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

    # Replit-specific configuration
    run_mode = os.getenv("RUN_MODE", "polling").lower()
    port = int(os.getenv("PORT", "5000"))
    from config import get_base_webhook_url

    webhook_url = get_base_webhook_url()
    
    # If running on Replit, prefer webhook if URL is provided
    if webhook_url and run_mode == "polling":
        run_mode = "webhook"

    logger.info("Starting Telegram Moderation Bot (%s mode)...", run_mode)

    application = Application.builder().token(BOT_TOKEN).job_queue(None).build()

    # Note: Job queue disabled on Python 3.13 due to weakref.__slots__ incompatibility
    # See: https://github.com/python-telegram-bot/python-telegram-bot/issues/3752
    # For Python 3.12 or lower, job_queue will work fine

    # Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("commands", commands_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("mystats", mystats_command))
    application.add_handler(CommandHandler("search", search_command))  # Updated from /vouches
    application.add_handler(CommandHandler("ask", ask_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("myvouches", myvouches_command))
    application.add_handler(CommandHandler("sync_vouches", sync_vouches_command))
    application.add_handler(CommandHandler("deletevouch", deletevouch_command))
    application.add_handler(CommandHandler("reminder", quick_reminder))
    application.add_handler(CommandHandler("add_keyword", add_keyword))
    application.add_handler(CommandHandler("remove_keyword", remove_keyword))
    application.add_handler(CommandHandler("list_keywords", list_keywords))
    # Debug command for admins to inspect recent vouches
    application.add_handler(CommandHandler("debug_vouches", debug_vouches))

    # Messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(CallbackQueryHandler(guide_callback, pattern="guide_.*"))
    application.add_handler(CallbackQueryHandler(help_callback, pattern="help_.*"))

    # Errors
    application.add_error_handler(error_handler)

    # Scheduled reminders disabled on Python 3.13 due to weakref issues
    # job_queue = application.job_queue
    # if job_queue:
    #     job_queue.run_repeating(...)
    logger.info("Scheduled jobs disabled on Python 3.13 (upgrade to Python 3.12 or lower for full features)")

    # Start the bot using the Application API
    try:
        if run_mode == "polling":
            logger.info("Starting bot in polling mode...")
            application.run_polling(allowed_updates=None, stop_signals=None)
        elif run_mode == "webhook":
            logger.info(f"Starting bot in webhook mode on port {port}...")
            # Build final webhook using the same helper in config so tests and
            # handle_missed_vouches() are aligned. Append BOT_TOKEN only if
            # not already present in the provided `WEBHOOK_URL`.
            from config import get_final_webhook_url
            final_webhook = get_final_webhook_url()

            # url_path should be just the token (the listening endpoint on this server).
            # Telegram will send POST requests to webhook_url (which includes the full path).
            # The Application will route them to the url_path internally.
            application.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=f"/{BOT_TOKEN}",
                webhook_url=final_webhook,
            )
        else:
            logger.error("Invalid RUN_MODE specified. Use 'polling' or 'webhook'.")
            return
    except Exception as e:
        logger.error(f"Bot failed to start: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
