"""
Telegram Moderation Bot - Production Grade
Multi-layer content moderation with strike system, rate limiting, and user statistics
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
from config import (
    BOT_TOKEN,
    ADMIN_ID,
    AUTO_DELETE_DELAY,
    MODERATION_MESSAGE,
    WELCOME_MESSAGE,
    STATS_MESSAGE,
    HELP_MESSAGE,
    MAX_STRIKES,
    STRIKE_RESET_HOURS,
    MUTE_DURATION_MINUTES,
)
from moderation import (
    check_message,
    track_user_activity,
    sanitize_text,
    extract_vouch_info,
    format_canonical_vouch,
    rewrite_vouch_with_ai,
)
from vouch_db import store_vouch, search_vouches, get_vouch_stats, format_vouch_for_display, update_vouch_message_id, check_vouch_duplicate_24h

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# User strike tracking: user_id -> {'strikes': int, 'last_violation': datetime, 'violations': []}
user_strikes = defaultdict(lambda: {'strikes': 0, 'last_violation': None, 'violations': []})

# Message deduplication: (chat_id, message_id) -> processing timestamp
# Prevents double-processing on offline recovery
processed_messages = {}
MESSAGE_DEDUP_WINDOW = 300  # 5 minutes - remove old entries

# Statistics tracking
stats = {
    'total_removed': 0,
    'last_24h': 0,
    'violations': defaultdict(int),
    'severity_counts': defaultdict(int),  # Count by severity
    'groups': set(),
    'last_reset': datetime.now(),
    'users_warned': 0,
    'users_muted': 0,
    'vouches_sanitized': 0,  # Track sanitized vouches
}

def reset_user_strikes_if_needed(user_id: int):
    """Reset user strikes if reset period has passed"""
    user_data = user_strikes[user_id]
    
    if user_data['last_violation'] and user_data['strikes'] > 0:
        time_since_last = datetime.now() - user_data['last_violation']
        if time_since_last > timedelta(hours=STRIKE_RESET_HOURS):
            logger.info(f"✓ Resetting strikes for user {user_id} (24h passed)")
            user_data['strikes'] = 0
            user_data['violations'] = []


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        WELCOME_MESSAGE,
        parse_mode='Markdown'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    await update.message.reply_text(HELP_MESSAGE, parse_mode='Markdown')


async def vouches_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /vouches command - search vouches by username"""
    args = context.args
    
    if not args:
        # Show vouch stats for this chat
        stats = get_vouch_stats(chat_id=update.effective_chat.id)
        stats_text = f"""
📊 **Vouch Statistics**

**Total Vouches:** {stats['total']}
**Positive:** {stats['positive']} ✅
**Negative:** {stats['negative']} ❌
**Sanitized:** {stats['sanitized']} 🛡️
**Last 24h:** {stats['recent_24h']}

Use `/vouches @username` to search for specific user vouches.
"""
        await update.message.reply_text(stats_text, parse_mode='Markdown')
        return
    
    # Search for vouches
    query = ' '.join(args)
    vouches = search_vouches(query, chat_id=update.effective_chat.id, limit=15)
    
    if not vouches:
        await update.message.reply_text(f"No vouches found for: {query}")
        return
    
    # Format results
    results = []
    for vouch in vouches:
        results.append(format_vouch_for_display(vouch))
    
    results_text = f"**Vouches for: {query}**\n\n" + "\n".join(results)
    
    if len(vouches) == 15:
        results_text += "\n\n_Showing first 15 results_"
    
    await update.message.reply_text(results_text, parse_mode='Markdown')


async def mystats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mystats command - show user's violation history"""
    user_id = update.effective_user.id
    reset_user_strikes_if_needed(user_id)
    
    user_data = user_strikes[user_id]
    
    if user_data['strikes'] == 0:
        await update.message.reply_text(
            "✅ **Your Status: Clean Record**\n\n"
            "You have no active violations. Keep up the good behavior!",
            parse_mode='Markdown'
        )
        return
    
    # Build violation history
    violation_list = "\n".join([
        f"  • {v['reason']} (Severity: {v['severity']})"
        for v in user_data['violations'][-5:]  # Show last 5
    ])
    
    status_text = f"""
⚠️ **Your Moderation Status**

**Strikes:** {user_data['strikes']}/{MAX_STRIKES}
**Last Violation:** {user_data['last_violation'].strftime('%Y-%m-%d %H:%M')}
**Recent Violations:**
{violation_list}

Strikes automatically reset after {STRIKE_RESET_HOURS} hours of no violations.
"""
    await update.message.reply_text(status_text, parse_mode='Markdown')


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command (admin only)"""
    user = update.effective_user
    
    if user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ This command is only available to admins.")
        return
    
    # Reset 24h counter if needed
    if datetime.now() - stats['last_reset'] > timedelta(hours=24):
        stats['last_24h'] = 0
        stats['last_reset'] = datetime.now()
    
    # Build top violations list
    top_violations = []
    for violation_type, count in sorted(stats['violations'].items(), key=lambda x: x[1], reverse=True)[:5]:
        top_violations.append(f"  • {violation_type}: {count}")
    
    top_violations_str = "\n".join(top_violations) if top_violations else "  None yet"
    
    # Build severity breakdown
    severity_breakdown = "\n".join([
        f"  • {severity.capitalize()}: {count}"
        for severity, count in sorted(stats['severity_counts'].items(), key=lambda x: x[1], reverse=True)
    ]) if stats['severity_counts'] else "  None yet"
    
    stats_text = STATS_MESSAGE.format(
        total_removed=stats['total_removed'],
        last_24h=stats['last_24h'],
        vouches_sanitized=stats['vouches_sanitized'],
        top_violations=top_violations_str,
        group_count=len(stats['groups']),
        users_warned=stats['users_warned'],
        users_muted=stats['users_muted'],
        severity_breakdown=severity_breakdown
    )
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')


async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Monitor and moderate group messages with strike system"""
    message = update.message
    
    # Only work in groups
    if message.chat.type not in ['group', 'supergroup']:
        return
    
    user_id = update.effective_user.id
    
    # Don't moderate admins
    if user_id == ADMIN_ID:
        return
    
    # Don't moderate bots
    if update.effective_user.is_bot:
        return
    
    # Message deduplication - prevent double-processing on offline recovery
    message_key = (message.chat.id, message.message_id)
    current_time = datetime.now()
    
    # Clean up old dedup entries (older than 5 minutes)
    stale_keys = [key for key, ts in processed_messages.items() 
                  if (current_time - ts).total_seconds() > MESSAGE_DEDUP_WINDOW]
    for key in stale_keys:
        del processed_messages[key]
    
    # Check if this message was already processed
    if message_key in processed_messages:
        logger.debug(f"Skipping duplicate message: chat={message.chat.id}, msg={message.message_id}")
        return
    
    # Mark this message as being processed
    processed_messages[message_key] = current_time
    
    # Check if message has text
    if not message.text:
        return
    
    # Track this group
    stats['groups'].add(message.chat.id)
    
    # Check rate limiting (spam prevention)
    is_rate_limited, rate_reason = track_user_activity(user_id, message.text)
    if is_rate_limited:
        try:
            await message.delete()
            logger.info(f"Rate limited user {user_id}: {rate_reason}")
            return
            
        except Exception as e:
            logger.error(f"Error handling rate limit: {e}")
            return
    
    # Check for content violations
    should_remove, reason, severity, is_vouch = await check_message(message.text, user_id)
    
    # Extract vouch info early if it's a vouch (needed for both clean and dirty vouches)
    vinfo = None
    if is_vouch:
        vinfo = extract_vouch_info(message.text, from_username=update.effective_user.username)

    # Only create canonical repost for vouches that are NOT being removed (clean vouches)
    if is_vouch and not should_remove:
        try:
            if vinfo:
                # Check if same person already vouched for this target within 24h
                is_duplicate_24h = check_vouch_duplicate_24h(
                    from_user_id=user_id,
                    to_username=vinfo['to_username'],
                    polarity=vinfo['polarity']
                )
                
                if is_duplicate_24h:
                    # Duplicate within 24h - don't store, but still reply to acknowledge
                    duplicate_note = f"📋 Vouch acknowledged (already vouched within 24h)"
                    try:
                        await message.reply_text(duplicate_note)
                    except Exception as e:
                        logger.warning(f"Failed to send duplicate vouch note: {e}")
                    logger.info(f"Vouch duplicate within 24h - skipped storage: user={user_id}, target={vinfo['to_username']}")
                else:
                    # Not a duplicate - ALWAYS store clean vouches
                    canonical_text = format_canonical_vouch(vinfo)
                    
                    # First: Store in database unconditionally (don't lose data)
                    db_success = store_vouch(
                        from_user_id=user_id,
                        from_username=update.effective_user.username,
                        from_display_name=update.effective_user.first_name,
                        to_user_id=None,  # Could be enhanced to resolve user ID from username
                        to_username=vinfo['to_username'].lstrip('@') if vinfo['to_username'] else None,
                        to_display_name=None,
                        polarity=vinfo['polarity'],
                        original_text=message.text,
                        canonical_text=canonical_text,
                        chat_id=message.chat.id,
                        message_id=message.message_id,  # Use original message ID
                        is_sanitized=False
                    )
                    
                    if not db_success:
                        logger.error(f"⚠️ CRITICAL: Failed to store clean vouch in database! User: {user_id}, Chat: {message.chat.id}")
                    
                    # Second: Optionally reply with canonical (if beneficial)
                    # Avoid reposting if original already contains the canonical text or if bot posted it
                    if canonical_text and canonical_text not in (message.text or '') and not update.effective_user.is_bot:
                        try:
                            sent_msg = await message.reply_text(canonical_text)
                            logger.info(f"✓ Clean vouch canonical reply sent: {vinfo['to_username']}")
                        except Exception as e:
                            logger.warning(f"Failed to send canonical reply: {e}")
                    else:
                        logger.info(f"✓ Clean vouch stored (no reply needed): {vinfo['to_username']}")
        except Exception as e:
            logger.error(f"Error creating canonical vouch repost: {e}")

    if should_remove:
        try:
            # Store original message details FIRST (before any deletion)
            original_text = message.text
            original_user = update.effective_user
            username = f"@{original_user.username}" if original_user.username else original_user.first_name
            message_id = message.message_id
            chat_id = message.chat.id

            # If it's a vouch, SANITIZE BEFORE DELETION to ensure nothing is lost
            if is_vouch:
                # Try AI-powered intelligent rewrite BEFORE deleting original
                rewritten = await rewrite_vouch_with_ai(original_text)
                
                if rewritten:
                    # AI successfully rewrote it - use the rewritten version
                    vouch_content = rewritten
                    sanitization_method = "AI Rewrite"
                else:
                    # AI failed or disabled - fallback to regex sanitization
                    sanitized = sanitize_text(original_text)
                    vouch_content = sanitized
                    sanitization_method = "Regex Sanitization"

                # Build vouch message regardless of vinfo (failsafe)
                vouch_message = f"{username}\n\n{vouch_content}"
                
                # ALWAYS pre-store dirty vouches BEFORE deletion (critical data preservation)
                # Extract fallback polarity/target if vinfo is None
                store_polarity = vinfo['polarity'] if vinfo else 'pos'  # Default to positive if unknown
                store_target = vinfo['to_username'].lstrip('@') if (vinfo and vinfo['to_username']) else 'unknown'
                
                temp_db_success = store_vouch(
                    from_user_id=user_id,
                    from_username=update.effective_user.username,
                    from_display_name=update.effective_user.first_name,
                    to_user_id=None,
                    to_username=store_target,
                    to_display_name=None,
                    polarity=store_polarity,
                    original_text=original_text,
                    canonical_text=vouch_message,
                    chat_id=chat_id,
                    message_id=0,  # Placeholder - will update after send
                    is_sanitized=True
                )
                
                if not temp_db_success:
                    logger.error(f"⚠️ CRITICAL: Failed to pre-store dirty vouch! User: {user_id}, Chat: {chat_id}")
                else:
                    logger.info(f"✓ Dirty vouch pre-stored before deletion (polarity: {store_polarity}, target: {store_target})")

                # NOW delete the violating original message
                try:
                    await message.delete()
                except Exception as e:
                    logger.warning(f"Failed to delete message {message_id}: {e}")

                # Send sanitized vouch message (can't reply to deleted message)
                try:
                    sent_msg = await message.chat.send_message(vouch_message, parse_mode='Markdown')
                    
                    # Update database with actual message_id after successful send (always, not just if vinfo)
                    update_vouch_message_id(chat_id, sent_msg.message_id)
                    logger.info(f"✓ Dirty vouch message_id updated after send: {sent_msg.message_id}")
                except Exception as e:
                    logger.error(f"Failed to send sanitized vouch: {e}")
                    # Vouch is already in DB with placeholder, so record isn't lost even if send failed

                logger.info(f"✓ Sanitized and reposted vouch from {user_id}: {reason}")

                # Don't give strikes for vouches - just sanitize them
                stats['total_removed'] += 1
                stats['last_24h'] += 1
                stats['violations']['Sanitized vouch'] += 1
                stats['severity_counts'][severity] += 1
                stats['vouches_sanitized'] += 1

                return  # Exit early - no strikes for vouches
            
            # NOT a vouch - delete the violating message immediately
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Failed to delete non-vouch message {message_id}: {e}")

            # Regular violation - track strikes (no automatic consequences - admins mute manually)
            reset_user_strikes_if_needed(user_id)
            user_data = user_strikes[user_id]
            user_data['strikes'] += 1
            user_data['last_violation'] = datetime.now()
            user_data['violations'].append({
                'reason': reason,
                'severity': severity,
                'timestamp': datetime.now()
            })

            current_strikes = user_data['strikes']

            # Update statistics
            stats['total_removed'] += 1
            stats['last_24h'] += 1
            stats['violations'][reason] += 1
            stats['severity_counts'][severity] += 1

            # Track strikes for admin reference (no automatic muting)
            stats['users_warned'] += 1

            logger.info(
                f"Removed [{severity}] from {user_id} in {message.chat.title}: {reason} (Strike {current_strikes}/3)"
            )

        except Exception as e:
            logger.error(f"Error moderating message: {e}")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")


def main():
    """Start the bot with webhook mode"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set in environment variables!")
        return
    
    if not ADMIN_ID or ADMIN_ID == 0:
        logger.error("❌ ADMIN_ID not set in environment variables!")
        return
    
    logger.info("🛡️ Starting Telegram Moderation Bot - Webhook Mode...")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("mystats", mystats_command))
    application.add_handler(CommandHandler("vouches", vouches_command))
    
    # Add message handler for moderation
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, moderate_message)
    )
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Get webhook URL from environment (Replit provides REPLIT_DEV_DOMAIN)
    import os
    replit_domain = os.getenv('REPLIT_DEV_DOMAIN')
    
    if replit_domain:
        webhook_url = f"https://{replit_domain}/webhook"
        logger.info(f"✓ Webhook URL: {webhook_url}")
    else:
        # Fallback for local testing
        webhook_url = "https://your-repl-url.replit.dev/webhook"
        logger.warning("⚠️  REPLIT_DEV_DOMAIN not found, using placeholder URL")
    
    # Start webhook server
    logger.info("✓ Bot started successfully!")
    logger.info(f"✓ Admin ID: {ADMIN_ID}")
    logger.info(f"✓ Strike System: Tracking {MAX_STRIKES} strikes (manual admin muting)")
    logger.info(f"✓ Detection Patterns: 100+ keywords, domains, and regex patterns")
    logger.info("✓ Add this bot to your group as an admin with delete + restrict permissions")
    logger.info("✓ Running in WEBHOOK mode (Autoscale-compatible)")
    
    # Run webhook on port 5000 (required for Replit Autoscale)
    application.run_webhook(
        listen="0.0.0.0",
        port=5000,
        url_path="/webhook",
        webhook_url=webhook_url,
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == '__main__':
    main()
