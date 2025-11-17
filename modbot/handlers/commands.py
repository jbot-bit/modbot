from __future__ import annotations

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler

logger = logging.getLogger(__name__)

from config import ADMIN_ID, WELCOME_MESSAGE, HELP_MAIN, HELP_VOUCHING, HELP_COMMANDS, HELP_MODERATION, HELP_TIPS
from moderation_engine.engine import BANNED_WORDS
from vouch_db import get_vouch_stats, search_vouches, format_vouch_for_display, delete_vouch_by_message, get_top_vouchers, count_user_vouches
from vouch_db import get_recent_vouches, get_last_vouch_timestamp, get_last_scanned_message_id, update_sync_state, get_sync_stats
from modbot.services.metrics import stats, roll_24h_if_needed


async def checkvouch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin-only. Reply to a message to check if it is logged as a vouch.
    Usage: /checkvouch (as a reply)
    """
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Admin only command.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Usage: Reply to a vouch message with /checkvouch.")
        return

    chat_id = update.effective_chat.id
    message_id = update.message.reply_to_message.message_id

    # Check if vouch is logged
    from vouch_db import search_vouches
    vouches = search_vouches("", chat_id=chat_id, limit=1000)  # Get all vouches for this chat (or optimize if possible)
    found = any(v.get("message_id") == message_id for v in vouches)
    if found:
        await update.message.reply_text("✅ This message is logged as a vouch.")
    else:
        await update.message.reply_text("❌ This message is NOT logged as a vouch.")


async def addvouch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin-only. Reply to a message to manually log it as a vouch if not already logged.
    Usage: /addvouch (as a reply)
    """
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Admin only command.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Usage: Reply to a vouch message with /addvouch.")
        return

    chat_id = update.effective_chat.id
    message_id = update.message.reply_to_message.message_id

    # Check if vouch is already logged
    from vouch_db import search_vouches
    vouches = search_vouches("", chat_id=chat_id, limit=1000)
    found = any(v.get("message_id") == message_id for v in vouches)
    if found:
        await update.message.reply_text("✅ This message is already logged as a vouch.")
        return

    # Try to log the vouch using the same logic as live vouch handling
    from moderation_engine.engine import is_vouch
    from modbot.services.vouches import handle_clean_vouch
    msg = update.message.reply_to_message
    if not msg.text or not is_vouch(msg.text):
        await update.message.reply_text("❌ The replied message does not look like a vouch.")
        return
    try:
        await handle_clean_vouch(msg)
        await update.message.reply_text("✅ Vouch has been logged.")
    except Exception as e:
        logger.error(f"Error logging vouch: {e}")
        await update.message.reply_text("❌ Failed to log vouch. Check logs for details.")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends the welcome message explaining the bot's purpose and key features.
    Triggered by the /start command.
    """
    await update.message.reply_text(
        WELCOME_MESSAGE,
        parse_mode="Markdown"
    )


async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Shows available commands directly.
    Triggered by the /commands command.
    """
    await update.message.reply_text(
        "Here are the available commands to help you navigate and use the bot effectively:\n\n"
        "- /help: Access the interactive help menu.\n"
        "- /leaderboard: View the top vouchers.\n"
        "- /myvouches: Check how many vouches you've given.\n"
        "- /search [@username]: Search for vouches related to a specific user.\n"
        "- /ask [@username]: Create a quick poll to ask if a user is vouched.\n"
        "- /mystats: View your moderation status.\n"
        "- /stats: Admin-only moderation dashboard.\n\n"
        "Our goal is to maintain a safe and welcoming community. Use these commands responsibly!",
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Provides an interactive help menu with inline keyboard buttons.
    Triggered by the /help command.
    """
    keyboard = [
        [InlineKeyboardButton("📝 Vouching", callback_data="help_vouching")],
        [InlineKeyboardButton("💬 Commands", callback_data="help_commands")],
        [InlineKeyboardButton("🛡️ Moderation", callback_data="help_moderation")],
        [InlineKeyboardButton("💡 Pro Tips", callback_data="help_tips")],
        [InlineKeyboardButton("📖 Full Guide", callback_data="help_full")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Welcome to our community bot! This group is dedicated to ensuring a safe and supportive environment for everyone. Use the buttons below to explore the bot's features:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def mystats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays the user's moderation status, including strikes and recent violations.
    Triggered by the /mystats command.
    """
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
    """
    Displays the moderation dashboard for admins.
    Triggered by the /stats command.
    """
    from modbot.services.metrics import stats

    roll_24h_if_needed()
    top_violations_str = "\n".join([
        f"• {k}: {v}" for k, v in stats["violations"].items()
    ])
    severity_breakdown = "\n".join([
        f"• {k}: {v}" for k, v in stats["severity_counts"].items()
    ])

    text = (
        "📊 **Moderation Dashboard**\n\n"
        f"**📈 Removal Statistics:**\n"
        f"• Total Removed: **{stats['total_removed']}** messages\n"
        f"• Last 24 Hours: **{stats['last_24h']}** messages\n"
        f"• Vouches Sanitized: **{stats['vouches_sanitized']}** 🛡️\n\n"
        f"**🎯 Top Violation Categories:**\n{top_violations_str}\n\n"
        f"**⚠️ Severity Breakdown:**\n{severity_breakdown}\n\n"
        f"**👥 User Management:**\n"
        f"• Protected Groups: **{len(stats['groups'])}**\n"
        f"• Users Warned: **{stats['users_warned']}**\n"
        f"• Users Muted: **{stats['users_muted']}**\n\n"
        "_Protecting your community 24/7_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "Use `/search @username` to search for specific user vouches."
        )
        await update.message.reply_text(stats_text, parse_mode="Markdown")
        return

    query = " ".join(args)
    vouches = search_vouches(query, chat_id=update.effective_chat.id, limit=50)
    logger.debug("Search for query=%s in chat=%s returned %d results", query, update.effective_chat.id, len(vouches))
    if not vouches:
        await update.message.reply_text(f"No vouches found for: {query}")
        return

    results = [format_vouch_for_display(v) for v in vouches[:15]]
    usernames = ", ".join(
        f"@{v['from_username']}" if v.get("from_username") else v.get("from_display_name", "Unknown")
        for v in vouches[:15]  # Limit to displayed vouches
    )
    count_line = f"Found {len(vouches)} vouch{'es' if len(vouches) != 1 else ''} for {query}."
    txt = f"**Vouches for: {query}**\n{count_line}\nFrom: {usernames}\n\n" + "\n".join(results)
    if len(vouches) > 15:
        txt += f"\n\n_Showing first 15 results, {len(vouches) - 15} more omitted_"
    await update.message.reply_text(txt, parse_mode="Markdown")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a quick poll to ask if a user is vouched"""
    if not context.args:
        await update.message.reply_text("Usage: /ask @username")
        return

    target = " ".join(context.args)
    question = f"Is {target} vouched?"
    try:
        await context.bot.send_poll(
            chat_id=update.effective_chat.id,
            question=question[:290],
            options=["👍 Vouched", "👎 Not vouched", "👀 I just want to see the results"],
            is_anonymous=False,
            allows_multiple_answers=False,
            reply_to_message_id=update.message.message_id,
        )
    except Exception:
        await update.message.reply_text("Couldn't create the poll right now. Try again shortly.")


async def quick_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a quick reminder about vouching and commands."""
    await update.message.reply_text(
        """
        Quick reminder 👋
        This group is run by the community for the community.
        Vouch for users to show support. Remember to vouch back.

        Want to know if someone is vouched?
        /search @user ➜ history of vouches
        If no history, try:
        /ask @user ➜ creates poll for the people to answer

        Keep it clean.
        """,
        parse_mode="Markdown"
    )


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Display top vouchers for a time period (default 7 days).
    Perfect for tracking competition winners.
    Usage: /leaderboard [days]
    Example: /leaderboard 7 (shows top vouchers from last week)
    """
    # Parse optional days argument
    days = 7  # Default to weekly
    if context.args:
        try:
            days = int(context.args[0])
            if days < 1 or days > 365:
                await update.message.reply_text("❌ Days must be between 1 and 365")
                return
        except ValueError:
            await update.message.reply_text("❌ Usage: /leaderboard [days]\nExample: /leaderboard 7")
            return
    
    chat_id = update.effective_chat.id
    top_vouchers = get_top_vouchers(chat_id=chat_id, days=days, limit=10, polarity="pos")
    
    if not top_vouchers:
        await update.message.reply_text(f"📊 No vouches in the last {days} day(s).")
        return
    
    # Format leaderboard
    leaderboard_text = f"🏆 **Top Vouchers (Last {days} Day{'s' if days != 1 else ''})**\n\n"
    
    for idx, voucher in enumerate(top_vouchers, 1):
        # Display username or user ID
        display_name = (
            f"@{voucher['from_username']}" if voucher['from_username'] 
            else voucher['from_display_name'] or f"User #{voucher['from_user_id']}"
        )
        
        # Add medal emoji for top 3
        medal = ""
        if idx == 1:
            medal = "🥇 "
        elif idx == 2:
            medal = "🥈 "
        elif idx == 3:
            medal = "🥉 "
        else:
            medal = f"{idx}. "
        
        leaderboard_text += f"{medal}{display_name}: **{voucher['vouch_count']}** vouches\n"
    
    await update.message.reply_text(leaderboard_text, parse_mode="Markdown")


async def myvouches_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Show how many vouches the user has given in a time period.
    Usage: /myvouches [days]
    Example: /myvouches 7 (shows your vouches from last week)
    """
    # Parse optional days argument
    days = 7  # Default to weekly
    if context.args:
        try:
            days = int(context.args[0])
            if days < 1 or days > 365:
                await update.message.reply_text("❌ Days must be between 1 and 365")
                return
        except ValueError:
            await update.message.reply_text("❌ Usage: /myvouches [days]\nExample: /myvouches 7")
            return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    try:
        # Count positive and negative vouches
        pos_count = count_user_vouches(user_id, chat_id=chat_id, days=days, polarity="pos")
        neg_count = count_user_vouches(user_id, chat_id=chat_id, days=days, polarity="neg")
        
        # Handle None or invalid returns from database
        if pos_count is None or neg_count is None:
            pos_count = pos_count or 0
            neg_count = neg_count or 0
        
        total = pos_count + neg_count
        
        if total == 0:
            await update.message.reply_text(f"📝 You haven't given any vouches in the last {days} day(s).")
            return
        
        text = (
            f"📊 **Your Vouches (Last {days} Day{'s' if days != 1 else ''})**\n\n"
            f"✅ Positive: **{pos_count}**\n"
            f"⚠️ Negative: **{neg_count}**\n"
            f"📈 Total: **{total}**"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error retrieving vouch count for user {user_id}: {e}")
        await update.message.reply_text("❌ Unable to retrieve vouch data. Please try again later.")


# In-memory dynamic configuration (for demonstration purposes)
dynamic_banned_words = set(BANNED_WORDS)

async def add_keyword(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Admin only command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /add_keyword <keyword>")
        return

    keyword = " ".join(context.args).strip()
    dynamic_banned_words.add(keyword)
    await update.message.reply_text(f"✅ Added keyword: {keyword}")

async def remove_keyword(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Admin only command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /remove_keyword <keyword>")
        return

    keyword = " ".join(context.args).strip()
    if keyword in dynamic_banned_words:
        dynamic_banned_words.remove(keyword)
        await update.message.reply_text(f"✅ Removed keyword: {keyword}")
    else:
        await update.message.reply_text(f"⚠️ Keyword not found: {keyword}")

async def list_keywords(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Admin only command.")
        return

    if not dynamic_banned_words:
        await update.message.reply_text("No banned keywords configured.")
        return

    keywords = "\n".join(sorted(dynamic_banned_words))
    await update.message.reply_text(f"🚫 **Banned Keywords:**\n{keywords}", parse_mode="Markdown")


async def debug_vouches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only command to list recent vouches in the current chat for debugging."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Admin only command.")
        return

    chat_id = update.effective_chat.id
    vouches = get_recent_vouches(chat_id=chat_id, limit=15)
    if not vouches:
        await update.message.reply_text("No recent vouches found in this chat.")
        return

    lines = [format_vouch_for_display(v) for v in vouches]
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def deletevouch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Delete a vouch by replying to it with /deletevouch
    
    Users can only delete their own vouches. Admins can delete any vouch.
    """
    # Check if this is a reply to a message
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ **Usage:** Reply to a vouch with `/deletevouch` to delete it.\n\n"
            "You can only delete your own vouches.\n"
            "_(Admins can delete any vouch)_",
            parse_mode="Markdown"
        )
        return
    
    replied_message = update.message.reply_to_message
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_id = replied_message.message_id
    is_admin = user_id == ADMIN_ID
    
    # Attempt to delete the vouch from database
    success, message = delete_vouch_by_message(message_id, chat_id, user_id, is_admin=is_admin)
    
    if success:
        # Delete the actual vouch message from Telegram
        try:
            await replied_message.delete()
        except Exception as e:
            logger.warning(f"Could not delete vouch message from Telegram: {e}")
            message += "\n\n⚠️ Vouch removed from database but message deletion failed (may be too old)."
        
        # Delete the command message
        try:
            await update.message.delete()
        except Exception:
            pass
        
        # Send temporary confirmation
        try:
            confirmation = await update.effective_chat.send_message(
                f"✅ {message}\n\n_(This message will disappear in 10 seconds)_",
                parse_mode="Markdown"
            )
            # Schedule deletion
            import asyncio
            asyncio.create_task(_delete_after_delay(confirmation, 10))
        except Exception:
            pass
    else:
        await update.message.reply_text(
            f"{message}",
            parse_mode="Markdown"
        )


async def sync_vouches_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sync vouches posted in the chat while the bot was offline.
    Usage: /sync_vouches
    Optional: /sync_vouches reset (to clear sync history and rescan everything)
    """
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Admin only command.")
        return

    chat_id = update.effective_chat.id

    # Check for reset flag
    reset = False
    if context.args and context.args[0].lower() == 'reset':
        reset = True

    # Get the last scanned message ID
    last_scanned_id = get_last_scanned_message_id(chat_id) if not reset else None

    processing_message = await update.message.reply_text(
        f"🔄 **Syncing vouches...**\n\n"
        f"{'Resetting sync history...' if reset else 'Resuming from last scanned message.'}\n\n"
        "Processing messages..."
    )

    try:
        # Fetch messages from the chat history
        updates = await context.bot.get_updates(offset=last_scanned_id + 1 if last_scanned_id else 0)
        scanned_count = 0
        vouch_count = 0

        for update in updates:
            if update.message and update.message.text:
                # Check if the message contains a vouch
                from moderation_engine.engine import is_vouch

                if is_vouch(update.message.text):
                    # Process the vouch
                    from modbot.services.vouches import handle_clean_vouch

                    try:
                        await handle_clean_vouch(update.message)
                        vouch_count += 1
                    except Exception as e:
                        logger.error(f"Failed to process vouch: {e}")

                # Update the last scanned message ID
                scanned_count += 1
                last_scanned_id = update.update_id

        # Update the sync state in the database
        update_sync_state(chat_id, last_scanned_id, vouch_count)

        # Provide feedback to the user
        await processing_message.edit_text(
            f"✅ **Sync Complete**\n\n"
            f"Messages scanned: **{scanned_count}**\n"
            f"Vouches found: **{vouch_count}**\n"
            f"Last scanned message ID: **{last_scanned_id}**"
        )

    except Exception as e:
        logger.error(f"Error during vouch sync: {e}")
        await processing_message.edit_text(
            "❌ **Sync Failed**\n\n"
            "An error occurred while syncing vouches. Check the logs for details."
        )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles inline keyboard callbacks for the help system.
    """
    query = update.callback_query
    await query.answer()

    callback_data = query.data

    # Main help menu with back button
    back_keyboard = [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="help_main")]]

    if callback_data == "help_main":
        keyboard = [
            [InlineKeyboardButton("📝 Vouching", callback_data="help_vouching")],
            [InlineKeyboardButton("💬 Commands", callback_data="help_commands")],
            [InlineKeyboardButton("🛡️ Moderation", callback_data="help_moderation")],
            [InlineKeyboardButton("💡 Pro Tips", callback_data="help_tips")],
            [InlineKeyboardButton("📖 Full Guide", callback_data="help_full")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            HELP_MAIN,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    elif callback_data == "help_vouching":
        reply_markup = InlineKeyboardMarkup(back_keyboard)
        await query.edit_message_text(
            HELP_VOUCHING,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    elif callback_data == "help_commands":
        reply_markup = InlineKeyboardMarkup(back_keyboard)
        await query.edit_message_text(
            HELP_COMMANDS,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    elif callback_data == "help_moderation":
        reply_markup = InlineKeyboardMarkup(back_keyboard)
        await query.edit_message_text(
            HELP_MODERATION,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    elif callback_data == "help_tips":
        reply_markup = InlineKeyboardMarkup(back_keyboard)
        await query.edit_message_text(
            HELP_TIPS,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    elif callback_data == "help_full":
        # Show the complete help message
        from config import HELP_MESSAGE
        reply_markup = InlineKeyboardMarkup(back_keyboard)
        await query.edit_message_text(
            HELP_MESSAGE,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )


async def _delete_after_delay(message, delay: int):
    """Helper to delete a message after a delay"""
    import asyncio
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


async def handle_missed_vouches(context: ContextTypes.DEFAULT_TYPE):
    """Fetch and log vouches posted while the bot was disconnected."""
    try:
        # Delete the webhook to allow getUpdates. Some Bot implementations
        # (like DummyBot in tests) may not implement delete_webhook; handle
        # that gracefully and continue processing updates.
        try:
            await context.bot.delete_webhook()
        except AttributeError:
            logger.debug("Bot does not implement delete_webhook; skipping")
        except Exception as e:
            # On any other error, log but continue
            logger.debug("delete_webhook raised an exception: %s", e)

        # Pull any queued updates (messages sent while bot was offline)
        updates = await context.bot.get_updates()
        for update in updates:
            if update.message and update.message.text:
                # Check if the message contains a vouch. Use moderation-layer helper
                from moderation_engine.engine import is_vouch

                if not getattr(update.message, "text", None):
                    continue
                if not is_vouch(update.message.text or ""):
                    continue

                # Extract relevant data
                from_user = update.message.from_user
                chat_id = update.message.chat_id
                message_id = update.message.message_id
                text = update.message.text

                # Re-run the same handling as live messages using the vouches handler
                # This will detect multiple targets, dedupe, and store each vouch
                from modbot.services.vouches import handle_clean_vouch

                try:
                    await handle_clean_vouch(update.message, from_username=from_user.username)
                except Exception as e:
                    logger.debug(f"Failed to process missed vouch for message {message_id}: {e}")

        # Clear the processed updates from Telegram so they won't be returned again
        if updates:
            last_id = updates[-1].update_id
            try:
                await context.bot.get_updates(offset=last_id + 1)
            except Exception:
                # Not critical; just log and continue
                logger.debug("Could not clear updates offset")
        logger.info("Missed vouches have been logged successfully.")
    except Exception as e:
        logger.error(f"Failed to handle missed vouches: {e}")
    finally:
        # Reconnect the webhook to ensure the bot continues running in webhook mode
        # Use the same WEBHOOK_URL that `bot_refactored.py` uses so the token path matches
        try:
            from config import BOT_TOKEN, get_base_webhook_url

            from config import get_final_webhook_url
            final_webhook = get_final_webhook_url()

            logger.info("Setting webhook to: %s", final_webhook)
            await context.bot.set_webhook(final_webhook)
            logger.info("Webhook reconnected successfully.")
        except Exception as e:
            logger.error(f"Failed to reconnect webhook: {e}")
