"""
PRIME DIRECTIVE BOT
"Protect the Group at All Costs"

No database. No gamification. No strikes. Just pure protection.

Workflow:
1. Every message → Check if vouch
2. If vouch → Sanitize & repost
3. If not vouch → Run through 3-layer funnel
4. Delete violations instantly
"""
import logging
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from config_prime import (
    BOT_TOKEN,
    ADMIN_ID,
    FORWARD_GROUP_ID,
    WELCOME_MESSAGE,
    HELP_MESSAGE,
    VOUCH_REPOST_TEMPLATE,
    VELOCITY_WARNING,
    NEW_USER_WARNING,
    VELOCITY_MUTE_DURATION,
)
from moderation_prime import (
    is_vouch,
    sanitize_vouch,
    check_violation,
    track_user_join,
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Statistics (minimal - just for admin visibility)
stats = {
    'total_deleted': 0,
    'vouches_sanitized': 0,
    'layer1_blocks': 0,
    'layer2_blocks': 0,
    'layer3_blocks': 0,
    'velocity_mutes': 0,
    'started': datetime.now(),
}


# ============================================================================
# COMMAND HANDLERS
# ============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start - Show welcome message"""
    await update.message.reply_text(WELCOME_MESSAGE, parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help - Show help message"""
    await update.message.reply_text(HELP_MESSAGE, parse_mode='Markdown')


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats - Show protection statistics (admin only)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Admin only command.")
        return
    
    uptime = datetime.now() - stats['started']
    hours = uptime.total_seconds() / 3600
    
    stats_text = f"""📊 **Protection Statistics**

**Overall:**
• Total Deleted: {stats['total_deleted']}
• Vouches Sanitized: {stats['vouches_sanitized']}

**By Layer:**
• Layer 1 (Keywords): {stats['layer1_blocks']}
• Layer 2 (AI): {stats['layer2_blocks']}
• Layer 3 (Behavior): {stats['layer3_blocks']}

**Behavior Control:**
• Velocity Mutes: {stats['velocity_mutes']}

**Uptime:** {hours:.1f} hours

_Prime Directive: Protect the group._ 🛡️
"""
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')


# ============================================================================
# MAIN MODERATION HANDLER - THE PRIME DIRECTIVE
# ============================================================================

async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    THE PRIME DIRECTIVE HANDLER (OPTIMIZED)
    
    Every message goes through this workflow:
    1. Quick access control checks (group, admin, bot)
    2. Forward message to log group (if configured)
    3. Check if vouch → Sanitize & repost
    4. If not vouch → Run through 3-layer funnel
    5. Delete violations instantly
    
    OPTIMIZATIONS:
    - Early exit for non-groups, admins, bots
    - Skip forwarding if no FORWARD_GROUP_ID
    - Fast vouch detection (pre-compiled regex)
    - Skip text processing if no text
    """
    message = update.message
    
    # Quick access control - exit early if not applicable
    if message.chat.type not in ('group', 'supergroup'):
        return
    
    # Check admin and bot in one go
    user_id = update.effective_user.id
    if user_id == ADMIN_ID or update.effective_user.is_bot:
        return
    
    # Forward message (if configured) - non-blocking
    if FORWARD_GROUP_ID:
        try:
            await context.bot.forward_message(
                chat_id=FORWARD_GROUP_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
        except Exception as e:
            logger.debug(f"[FORWARD] Failed: {e}")
    
    # Track user (for Layer 3 new user restrictions)
    track_user_join(user_id)
    
    # Early exit if no text (no moderation needed)
    text = message.text
    if not text:
        return
    
    # ========================================================================
    # STEP 1: VOUCH INTENT CHECK (First Check - OPTIMIZED)
    # ========================================================================
    
    if is_vouch(text):
        try:
            # Check if the vouch contains any violations
            has_violation, violation_reason, _ = await check_violation(text, user_id, message)
            
            # If vouch is CLEAN, leave it alone (early exit)
            if not has_violation:
                return
            
            # Vouch has violations - sanitize and repost
            author = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
            timestamp = message.date.strftime("%Y-%m-%d %H:%M:%S UTC") if message.date else "Unknown"
            user_id = update.effective_user.id
            
            # Delete, sanitize, repost in one try block
            await message.delete()
            sanitized_text = sanitize_vouch(text)
            
            await message.chat.send_message(
                VOUCH_REPOST_TEMPLATE.format(author=author, timestamp=timestamp, sanitized_text=sanitized_text),
                parse_mode='Markdown'
            )
            
            stats['vouches_sanitized'] += 1
            return
            
        except Exception as e:
            logger.error(f"[VOUCH] Error: {e}")
            return
    
    # ========================================================================
    # STEP 2: NON-VOUCH MESSAGE - RUN THROUGH
    # ========================================================================
    
    try:
        should_delete, reason, layer = await check_violation(text, user_id, message)
        
        if not should_delete:
            return  # Early exit - message is clean
        
        # Delete the violating message
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Failed to delete message: {e}")
        
        # Notify user about the deletion
        try:
            notification_msg = await message.chat.send_message(
                "Comment removed. Use cleaner language.",
                parse_mode='Markdown'
            )
            # Auto-delete notification after 10 seconds
            asyncio.create_task(_delete_message_delayed(notification_msg, 10))
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

        # Update stats based on layer
        stats['total_deleted'] += 1
        if layer == "Layer1":
            stats['layer1_blocks'] += 1
        elif layer == "Layer2":
            stats['layer2_blocks'] += 1
        elif layer.startswith("Layer3"):
            stats['layer3_blocks'] += 1
        
        # Handle velocity violations (mute user)
        if layer == "Layer3-Velocity":
            try:
                until_date = datetime.now() + timedelta(seconds=VELOCITY_MUTE_DURATION)
                await context.bot.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until_date
                )
                
                warning_msg = await message.chat.send_message(
                    f"@{update.effective_user.username or update.effective_user.first_name}, {VELOCITY_WARNING}",
                    parse_mode='Markdown'
                )
                stats['velocity_mutes'] += 1
                
                # Auto-delete warning after 10 seconds (non-blocking)
                asyncio.create_task(_delete_message_delayed(warning_msg, 10))
                
            except Exception as e:
                logger.error(f"Mute failed: {e}")
        
        # Handle new user restriction violations
        elif layer == "Layer3-NewUser":
            try:
                warning_msg = await message.chat.send_message(
                    f"@{update.effective_user.username or update.effective_user.first_name}, {NEW_USER_WARNING}",
                    parse_mode='Markdown'
                )
                # Auto-delete warning after 15 seconds (non-blocking)
                asyncio.create_task(_delete_message_delayed(warning_msg, 15))
                
            except Exception as e:
                logger.error(f"Warning failed: {e}")
        
    except Exception as e:
        logger.error(f"Moderation error: {e}")


async def _delete_message_delayed(msg, delay: int):
    """Helper to delete message after delay (non-blocking)"""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except:
        pass


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")


# ============================================================================
# MAIN FUNCTION - START THE BOT
# ============================================================================

def main():
    """Start the Prime Directive protection bot"""
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set in environment variables!")
        return
    
    if not ADMIN_ID or ADMIN_ID == 0:
        logger.error("❌ ADMIN_ID not set in environment variables!")
        return
    
    logger.info("="*60)
    logger.info("🛡️  PRIME DIRECTIVE BOT STARTING")
    logger.info("="*60)
    logger.info("Goal: Protect the group from being shut down")
    logger.info("Method: 3-layer protection funnel")
    logger.info("Special: Vouch sanitization workflow")
    logger.info("="*60)
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Add main moderation handler
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, moderate_message)
    )
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    logger.info("✅ Bot started successfully!")
    logger.info(f"✅ Admin ID: {ADMIN_ID}")
    logger.info(f"✅ Protection layers: 3 (Keyword + AI + Behavior)")
    logger.info(f"✅ Vouch system: Active (sanitize & repost)")
    logger.info("="*60)
    logger.info("🛡️  THE SHIELD IS NOW ACTIVE")
    logger.info("="*60)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
