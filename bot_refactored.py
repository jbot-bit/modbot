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
    checkvouch_command,
    addvouch_command,
    debug_vouches,
    quick_reminder,
    handle_missed_vouches,
    debug_webhook,
    reset_webhook,
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
        logger.error(f"=== ERROR IN BOT ===")
        logger.error(f"Update: {update}")
        logger.error(f"Error: {context.error}")
        logger.error(f"Error type: {type(context.error)}")
        import traceback
        if context.error:
            logger.error(f"Error traceback: {''.join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))}")
    except Exception as e:
        logger.error(f"Error handler failed: {e}", exc_info=True)


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
    # Fetch environment variables dynamically
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # Default to 0 if not set

    # Ensure required environment variables are set
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set in environment variables!")
        exit(1)
    if not ADMIN_ID:
        logger.error("ADMIN_ID not set in environment variables!")
        exit(1)

    # Webhook mode configuration
    run_mode = "webhook"
    port = int(os.getenv("PORT", "5000"))

    # Use WEBHOOK_URL from secrets
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if not WEBHOOK_URL:
        logger.error("WEBHOOK_URL not set in environment variables!")
        exit(1)

    logger.info("Starting Telegram Moderation Bot (webhook mode)...")
    logger.info(f"BOT_TOKEN prefix: {BOT_TOKEN[:30]}...")
    logger.info(f"WEBHOOK_URL: {WEBHOOK_URL}")

    application = Application.builder().token(BOT_TOKEN).job_queue(None).build()

    logger.info("=== BOT APPLICATION INITIALIZED ===")
    logger.info(f"Bot token: {BOT_TOKEN[:20]}...")
    logger.info(f"Admin ID: {ADMIN_ID}")
    logger.info(f"Webhook URL: {WEBHOOK_URL}")
    logger.info(f"Port: {port}")

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
    application.add_handler(CommandHandler("checkvouch", checkvouch_command))
    application.add_handler(CommandHandler("addvouch", addvouch_command))
    application.add_handler(CommandHandler("reminder", quick_reminder))
    application.add_handler(CommandHandler("add_keyword", add_keyword))
    application.add_handler(CommandHandler("remove_keyword", remove_keyword))
    application.add_handler(CommandHandler("list_keywords", list_keywords))
    # Debug command for admins to inspect recent vouches
    application.add_handler(CommandHandler("debug_vouches", debug_vouches))
    application.add_handler(CommandHandler("debug_webhook", debug_webhook))
    application.add_handler(CommandHandler("reset_webhook", reset_webhook))

    # Messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(CallbackQueryHandler(guide_callback, pattern="guide_.*"))
    application.add_handler(CallbackQueryHandler(help_callback, pattern="help_.*"))

    # Errors
    application.add_error_handler(error_handler)

    logger.info("=== ALL HANDLERS REGISTERED ===")
    logger.info(f"Handlers object type: {type(application.handlers)}")
    logger.info(f"Handlers content: {application.handlers}")
    handler_count = sum(len(h) for h in application.handlers.values()) if isinstance(application.handlers, dict) else len(application.handlers)
    logger.info(f"Total handlers: {handler_count}")

    # Scheduled reminders disabled on Python 3.13 due to weakref issues
    # job_queue = application.job_queue
    # if job_queue:
    #     job_queue.run_repeating(...)
    logger.info("Scheduled jobs disabled on Python 3.13 (upgrade to Python 3.12 or lower for full features)")

    # Validate and log the webhook URL
    from config import validate_webhook_url
    try:
        final_webhook_url = validate_webhook_url()
        logger.info(f"Using webhook URL: {final_webhook_url}")
    except ValueError as e:
        logger.error(f"Invalid webhook URL: {e}")
        exit(1)

    logger.info("=== VALIDATED WEBHOOK URL SUCCESSFULLY ===")

    # Start the bot using the Application API
    logger.info(f"Starting bot in webhook mode on port {port}...")
    logger.info(f"Webhook URL: {WEBHOOK_URL}")
    logger.info("Registering webhook and starting listener...")
    logger.info("=== WEBHOOK LISTENER STARTING - READY FOR INCOMING MESSAGES ===")
    
    # Construct the full webhook URL with token
    FULL_WEBHOOK_URL = f"{WEBHOOK_URL}/{BOT_TOKEN}"

    try:
        # Construct the url_path with token - this is where Telegram will send webhooks
        url_path_with_token = f"/webhook/{BOT_TOKEN}"
        logger.info(f"Listening on url_path: {url_path_with_token}")
        
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=url_path_with_token,
            webhook_url=FULL_WEBHOOK_URL,  # Ensure Telegram sends to the correct path
        )
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user")
    except Exception as e:
        logger.error(f"Bot failed to start: {e}", exc_info=True)
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        import traceback
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        raise


if __name__ == "__main__":
    main()
