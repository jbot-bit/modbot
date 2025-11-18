"""
Vouch Database Module
Stores canonical vouches in SQLite for persistence and searchability.
Handles cases where user accounts are deleted but vouches remain searchable.
"""
import sqlite3
import logging
from datetime import datetime, UTC
from typing import List, Dict, Optional
import os

logger = logging.getLogger(__name__)

DB_PATH = "vouches.db"
# Number of seconds a user has to retry a vouch before their attempt counter resets
VOUCH_RETRY_WINDOW_SECONDS = 5 * 60  # 5 minutes


def get_db_connection():
    """Get a database connection with WAL mode and concurrent access optimizations."""
    conn = sqlite3.connect(DB_PATH)
    # Enable WAL mode for concurrent reads/writes
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA timeout=5000")  # 5 second timeout for locked DB
    return conn


def _normalize_for_index(s: Optional[str]) -> Optional[str]:
    """Normalize strings for DB searches (lowered, None for empty)."""
    if not s:
        return None
    return s.lower()


def check_vouch_duplicate_24h(
    from_user_id: int,
    to_username: Optional[str],
    polarity: str
) -> bool:
    """
    Check if same person vouched for same target within last 24 hours.
    Prevents duplicate vouches within 24h window.
    
    Args:
        from_user_id: Telegram user ID of voucher
        to_username: Username of target (for matching)
        polarity: 'pos' or 'neg'
    
    Returns:
        True if duplicate exists within 24h, False otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check for same person vouching for same target in last 24 hours
        # Use numeric timestamp (epoch seconds) which we store in `timestamp`
        cursor.execute("""
        SELECT COUNT(*) FROM vouches 
        WHERE from_user_id = ? 
          AND to_username_lower = ?
          AND polarity = ?
          AND timestamp > (strftime('%s','now') - 86400)
    """, (from_user_id, _normalize_for_index(to_username), polarity))

        result = cursor.fetchone()[0] > 0
        conn.close()

        if result:
            logger.debug(f"24h vouch duplicate detected: user={from_user_id}, target={to_username}, polarity={polarity}")

        return result

    except Exception as e:
        logger.error(f"Failed to check vouch duplicate: {e}")
        return False  # On error, allow vouch (fail-open)


def get_prior_vouchers_for_target(to_username: Optional[str], polarity: str = "pos", limit: int = 5) -> List[Dict]:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT from_username, from_display_name, timestamp FROM vouches
            WHERE to_username_lower = ? AND polarity = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (_normalize_for_index(to_username), polarity, limit))

        rows = cursor.fetchall()
        conn.close()
        
        vouchers = []
        for row in rows:
            vouchers.append({
                "from_username": row[0],
                "from_display_name": row[1],
                "timestamp": row[2],
            })
        return vouchers
        
    except Exception as e:
        logger.error(f"Failed to fetch prior vouchers: {e}")
        return []


def track_vouch_retry_attempt(user_id: int, chat_id: int, target_username: str) -> int:
    """
    Track a failed vouch attempt (ToS violation). Returns the current attempt count.
    
    Args:
        user_id: Telegram user ID attempting the vouch
        chat_id: Chat where the vouch was attempted
        target_username: Username being vouched for (normalized)
    
    Returns:
        int: Current attempt count (1, 2, 3, etc.)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Ensure username normalization is consistent
        target_norm = target_username.lower().strip("@")
        now = datetime.now().timestamp()

        # Debug logging to trace SQL execution
        logger.debug(f"Normalized target username: {target_norm}")
        logger.debug("Checking if user-target pair exists...")

        cursor.execute("""
            SELECT attempt_count, last_attempt_time FROM vouch_retry_attempts
            WHERE user_id = ? AND chat_id = ? AND target_username = ?
        """, (user_id, chat_id, target_norm))

        existing_entry = cursor.fetchone()
        logger.debug(f"Existing entry: {existing_entry}")

        if not existing_entry:
            logger.debug("No existing entry found. Initializing counter...")
            # Initialize counter if no entry exists
            cursor.execute("""
                INSERT INTO vouch_retry_attempts (user_id, chat_id, target_username, attempt_count, last_attempt_time)
                VALUES (?, ?, ?, 1, ?)
            """, (user_id, chat_id, target_norm, now))
            attempt_count = 1
        else:
            prev_count, last_attempt_time = existing_entry
            # If the last attempt was outside the retry window, reset to 1
            if now - (last_attempt_time or 0) > VOUCH_RETRY_WINDOW_SECONDS:
                logger.debug("Previous attempt outside retry window - resetting counter to 1")
                cursor.execute("""
                    UPDATE vouch_retry_attempts
                    SET attempt_count = 1, last_attempt_time = ?
                    WHERE user_id = ? AND chat_id = ? AND target_username = ?
                """, (now, user_id, chat_id, target_norm))
                attempt_count = 1
            else:
                logger.debug("Existing entry within retry window - incrementing counter")
                cursor.execute("""
                    UPDATE vouch_retry_attempts
                    SET attempt_count = attempt_count + 1, last_attempt_time = ?
                    WHERE user_id = ? AND chat_id = ? AND target_username = ?
                """, (now, user_id, chat_id, target_norm))

                # Read back the incremented count
                cursor.execute("""
                    SELECT attempt_count FROM vouch_retry_attempts
                    WHERE user_id = ? AND chat_id = ? AND target_username = ?
                """, (user_id, chat_id, target_norm))
                result = cursor.fetchone()
                attempt_count = result[0] if result else 1
        
        conn.commit()
        conn.close()
        
        logger.info(f"Vouch retry tracked: user={user_id}, target={target_norm}, attempts={attempt_count}")
        return attempt_count
        
    except Exception as e:
        logger.error(f"Failed to track vouch retry: {e}")
        return 1  # Default to first attempt on error


def clear_vouch_retry_attempts(user_id: int, chat_id: int, target_username: str) -> None:
    """
    Clear retry attempts for a user after successful vouch posting.
    
    Args:
        user_id: Telegram user ID
        chat_id: Chat ID
        target_username: Target username (normalized)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        target_norm = (target_username or "").lstrip("@").lower()
        
        cursor.execute("""
            DELETE FROM vouch_retry_attempts
            WHERE user_id = ? AND chat_id = ? AND target_username = ?
        """, (user_id, chat_id, target_norm))
        
        conn.commit()
        conn.close()
        
        logger.debug(f"Cleared vouch retry attempts: user={user_id}, target={target_norm}")
        
    except Exception as e:
        logger.error(f"Failed to clear vouch retry attempts: {e}")


def cleanup_old_vouch_retry_attempts(hours: int = 24) -> None:
    """
    Clean up old vouch retry attempts older than specified hours.
    Called periodically to prevent table bloat.
    
    Args:
        hours: Age threshold in hours (default 24)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cutoff_time = datetime.now().timestamp() - (hours * 3600)
        
        cursor.execute("""
            DELETE FROM vouch_retry_attempts
            WHERE last_attempt_time < ?
        """, (cutoff_time,))
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old vouch retry attempts")
            
    except Exception as e:
        logger.error(f"Failed to cleanup vouch retry attempts: {e}")


def init_db():
    """Initialize the vouches database with required tables."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Create metrics table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS group_metrics (
                chat_id INTEGER PRIMARY KEY,
                last_active REAL
            )
            """
        )

        # Create vouches table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS vouches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER NOT NULL,
                from_username TEXT,
                from_display_name TEXT,
                from_username_lower TEXT,
                from_display_name_lower TEXT,
                to_user_id INTEGER,
                to_username TEXT,
                to_display_name TEXT,
                to_username_lower TEXT,
                to_display_name_lower TEXT,
                polarity TEXT NOT NULL,
                original_text TEXT,
                canonical_text TEXT,
                chat_id INTEGER,
                message_id INTEGER,
                is_sanitized INTEGER DEFAULT 0,
                timestamp REAL,
                created_at TEXT
            )
            """
        )

        # Create vouch retry attempts table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS vouch_retry_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                target_username TEXT,
                attempt_count INTEGER DEFAULT 1,
                last_attempt_time REAL NOT NULL,
                UNIQUE(user_id, chat_id, target_username)
            )
            """
        )

        # Cleanup vouch retry attempts table to remove stale data
        cursor.execute("DELETE FROM vouch_retry_attempts")
        logger.info("Cleared vouch retry attempts table during initialization.")

        # Create indexes for fast lookups
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON vouches(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_from_user_id ON vouches(from_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_to_user_id ON vouches(to_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_from_username_lower ON vouches(from_username_lower)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_to_username_lower ON vouches(to_username_lower)")
        
        # Create sync state table to track last scanned message per chat
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_state (
                chat_id INTEGER PRIMARY KEY,
                last_scanned_message_id INTEGER,
                last_sync_time REAL,
                vouches_found_total INTEGER DEFAULT 0
            )
            """
        )
        
        # username_history: map usernames to user ids when we first discover them
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS username_history (
                user_id INTEGER NOT NULL,
                username_lower TEXT NOT NULL,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_username_history_username ON username_history(username_lower)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_username_history_user ON username_history(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_retry_user_chat ON vouch_retry_attempts(user_id, chat_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_retry_time ON vouch_retry_attempts(last_attempt_time)")

        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")


def migrate_db():
    """Migrate existing database to add new columns if missing."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check and add missing columns to vouches table
        cursor.execute("PRAGMA table_info(vouches)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'from_username_lower' not in columns:
            cursor.execute("ALTER TABLE vouches ADD COLUMN from_username_lower TEXT")
            logger.info("Added from_username_lower column to vouches table")

        if 'to_username_lower' not in columns:
            cursor.execute("ALTER TABLE vouches ADD COLUMN to_username_lower TEXT")
            logger.info("Added to_username_lower column to vouches table")

        if 'from_display_name_lower' not in columns:
            cursor.execute("ALTER TABLE vouches ADD COLUMN from_display_name_lower TEXT")
            logger.info("Added from_display_name_lower column to vouches table")

        if 'to_display_name_lower' not in columns:
            cursor.execute("ALTER TABLE vouches ADD COLUMN to_display_name_lower TEXT")
            logger.info("Added to_display_name_lower column to vouches table")

        if 'created_at' not in columns:
            cursor.execute("ALTER TABLE vouches ADD COLUMN created_at TEXT")
            logger.info("Added created_at column to vouches table")

        conn.commit()
        conn.close()
        logger.info("Database migration completed successfully")
    except Exception as e:
        logger.error(f"Failed to migrate database: {e}")


def normalize_existing_vouches():
    """Normalize existing vouches to ensure case-insensitive matching."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Normalize from_username_lower and to_username_lower, including empty strings
        cursor.execute("""
            UPDATE vouches
            SET from_username_lower = LOWER(from_username)
            WHERE (from_username_lower IS NULL OR from_username_lower = '')
              AND from_username IS NOT NULL
        """)
        cursor.execute("""
            UPDATE vouches
            SET to_username_lower = LOWER(to_username)
            WHERE (to_username_lower IS NULL OR to_username_lower = '')
              AND to_username IS NOT NULL
        """)
        cursor.execute("""
            UPDATE vouches
            SET from_display_name_lower = LOWER(from_display_name)
            WHERE (from_display_name_lower IS NULL OR from_display_name_lower = '')
              AND from_display_name IS NOT NULL
        """)
        cursor.execute("""
            UPDATE vouches
            SET to_display_name_lower = LOWER(to_display_name)
            WHERE (to_display_name_lower IS NULL OR to_display_name_lower = '')
              AND to_display_name IS NOT NULL
        """)

        conn.commit()
        conn.close()
        logger.info("Normalized existing vouches successfully.")
    except Exception as e:
        logger.error(f"Failed to normalize vouches: {e}")


def vouch_exists_by_message_id(chat_id: int, message_id: int) -> bool:
    """
    Check if a vouch already exists for the given message_id in the chat.
    This prevents exact duplicates from being stored.
    
    Args:
        chat_id: Telegram chat ID
        message_id: Telegram message ID
    
    Returns:
        True if vouch exists, False otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM vouches WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id)
        )
        count = cursor.fetchone()[0]
        conn.close()
        logger.debug(f"vouch_exists_by_message_id: chat_id={chat_id}, message_id={message_id}, count={count}")
        return count > 0
    except Exception as e:
        logger.error(f"Failed to check if vouch exists: {e}")
        return False


def store_vouch(
    from_user_id: int,
    from_username: Optional[str],
    from_display_name: Optional[str],
    to_user_id: Optional[int],
    to_username: Optional[str],
    to_display_name: Optional[str],
    polarity: str,
    original_text: str,
    canonical_text: str,
    chat_id: int,
    message_id: Optional[int] = None,
    is_sanitized: bool = False
) -> bool:
    """
    Store a vouch in the database.
    
    Args:
        from_user_id: Telegram user ID of the voucher
        from_username: Username of voucher (without @)
        from_display_name: Display name of voucher
        to_user_id: Telegram user ID of target (if available)
        to_username: Username of target (without @)
        to_display_name: Display name of target
        polarity: 'pos' or 'neg'
        original_text: Original message text
        canonical_text: Canonical formatted text
        chat_id: Telegram chat ID
        message_id: Telegram message ID of canonical repost
        is_sanitized: Whether original was sanitized
    
    Returns:
        True if stored successfully, False otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Prevent duplicates: check if exact same vouch already exists (same chat, user, target, original_text)
        # For messages that vouch multiple targets, allow separate entries per target.
        to_username_lower = _normalize_for_index(to_username)

        if to_username_lower:
            cursor.execute("""
                SELECT COUNT(*) FROM vouches 
                WHERE chat_id = ? AND from_user_id = ? AND original_text = ? AND to_username_lower = ?
            """, (chat_id, from_user_id, original_text, to_username_lower))
        else:
            cursor.execute("""
                SELECT COUNT(*) FROM vouches 
                WHERE chat_id = ? AND from_user_id = ? AND original_text = ? AND to_username_lower IS NULL
            """, (chat_id, from_user_id, original_text))
        
        dup_count = cursor.fetchone()[0]
        if dup_count > 0:
            logger.info(f"⊘ Duplicate vouch skipped: chat={chat_id}, user={from_user_id}, target={to_username}, polarity={polarity}")
            conn.close()
            return False  # Already stored
        
        # Normalize text for fast case-insensitive searching
        from_username_lower = _normalize_for_index(from_username)
        to_username_lower = _normalize_for_index(to_username)
        from_display_name_lower = _normalize_for_index(from_display_name)
        to_display_name_lower = _normalize_for_index(to_display_name)
        
        # Prepare timestamps
        created_at = datetime.now(UTC).isoformat()
        timestamp_val = datetime.now(UTC).timestamp()

        cursor.execute("""
            INSERT INTO vouches (
                from_user_id, from_username, from_display_name,
                from_username_lower, from_display_name_lower,
                to_user_id, to_username, to_display_name,
                to_username_lower, to_display_name_lower,
                polarity, original_text, canonical_text,
                chat_id, message_id, is_sanitized,
                timestamp, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            from_user_id, from_username, from_display_name,
            from_username_lower, from_display_name_lower,
            to_user_id, to_username, to_display_name,
            to_username_lower, to_display_name_lower,
            polarity, original_text, canonical_text,
            chat_id, message_id, int(is_sanitized),
            timestamp_val, created_at
        ))
        
        conn.commit()
        conn.close()
        
        vouch_id = cursor.lastrowid
        logger.info(f"✓ Stored vouch ID={vouch_id}: {from_username or from_user_id} -> {to_username or to_user_id} ({polarity}), to_user_id={to_user_id}, chat={chat_id}, msg={message_id}, sanitized={is_sanitized}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to store vouch: {e}")
        return False


def delete_vouch_by_message(message_id: int, chat_id: int, user_id: int, is_admin: bool = False) -> tuple[bool, str]:
    """
    Delete a vouch from the database if it was posted by the requesting user (or by admin).
    
    Args:
        message_id: Telegram message ID of the vouch to delete
        chat_id: Telegram chat ID
        user_id: Telegram user ID requesting deletion (must match vouch author unless admin)
        is_admin: Whether the requesting user is an admin (can delete any vouch)
    
    Returns:
        Tuple of (success: bool, message: str)
        - success: True if deleted, False otherwise
        - message: Description of what happened
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # First check if vouch exists and belongs to this user
        cursor.execute("""
            SELECT from_user_id, from_username, to_username, polarity 
            FROM vouches 
            WHERE message_id = ? AND chat_id = ?
        """, (message_id, chat_id))
        
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return False, "No vouch found with that message ID."
        
        vouch_user_id, from_username, to_username, polarity = result
        
        # Check if user owns this vouch (or is admin)
        if vouch_user_id != user_id and not is_admin:
            conn.close()
            return False, "❌ You can only delete your own vouches."
        
        # Delete the vouch
        if is_admin:
            # Admin can delete any vouch
            cursor.execute("""
                DELETE FROM vouches 
                WHERE message_id = ? AND chat_id = ?
            """, (message_id, chat_id))
        else:
            # Regular user can only delete their own
            cursor.execute("""
                DELETE FROM vouches 
                WHERE message_id = ? AND chat_id = ? AND from_user_id = ?
            """, (message_id, chat_id, user_id))
        
        conn.commit()
        conn.close()
        
        polarity_emoji = "✅" if polarity == "pos" else "⚠️"
        admin_note = " (admin delete)" if is_admin and vouch_user_id != user_id else ""
        logger.info(f"✓ Deleted vouch{admin_note}: {from_username or user_id} -> {to_username} ({polarity})")
        return True, f"{polarity_emoji} Vouch deleted: {from_username or 'User'} → @{to_username}"
        
    except Exception as e:
        logger.error(f"Failed to delete vouch: {e}")
        return False, f"Error deleting vouch: {str(e)}"


def update_vouch_message_id(chat_id: int, message_id: int) -> bool:
    """
    Update the message_id for the most recently inserted vouch in a chat.
    Used for updating placeholder message_id after successful send.
    
    Args:
        chat_id: Telegram chat ID
        message_id: Telegram message ID to update
    
    Returns:
        True if updated successfully, False otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update the most recent vouch in this chat with message_id=0 (placeholder)
        # SQLite doesn't support ORDER BY/LIMIT in UPDATE directly; use subquery
        cursor.execute("""
            UPDATE vouches SET message_id = ?
            WHERE id = (
                SELECT id FROM vouches
                WHERE chat_id = ? AND message_id = 0
                ORDER BY timestamp DESC
                LIMIT 1
            )
        """, (message_id, chat_id))
        
        conn.commit()
        conn.close()
        
        if cursor.rowcount > 0:
            logger.info(f"✓ Updated vouch message_id: chat={chat_id}, msg={message_id}")
            return True
        else:
            logger.warning(f"No placeholder vouch found to update in chat {chat_id}")
            return False
        
    except Exception as e:
        logger.error(f"Failed to update vouch message_id: {e}")
        return False


def update_vouches_with_resolved_user_id(
    chat_id: Optional[int], username: str, user_id: int
) -> int:
    """
    When we later discover a resolved Telegram user id for a previously-unknown
    @username, update all vouches that targeted that username so future searches
    can match by user id as well. Returns the number of rows updated.

    Args:
        chat_id: Limit updates to a specific chat if provided, pass None to
                 update across all chats.
        username: Username (with or without @)
        user_id: Telegram user ID to set on matching vouches

    Returns:
        Number of rows updated.
    """
    try:
        if not username:
            return 0
        conn = get_db_connection()
        cursor = conn.cursor()

        norm = (username.lstrip("@")).lower()

        # Only update rows where to_user_id is NULL or 0 (not resolved yet)
        if chat_id is None:
            cursor.execute(
                """
                UPDATE vouches
                SET to_user_id = ?
                WHERE (to_username_lower = ? OR (to_username_lower IS NULL AND LOWER(to_username) = ?))
                  AND (to_user_id IS NULL OR to_user_id = 0)
            """,
                (user_id, norm, norm),
            )
        else:
            cursor.execute(
                """
                UPDATE vouches
                SET to_user_id = ?
                WHERE (to_username_lower = ? OR (to_username_lower IS NULL AND LOWER(to_username) = ?))
                  AND chat_id = ?
                  AND (to_user_id IS NULL OR to_user_id = 0)
            """,
                (user_id, norm, norm, chat_id),
            )

        updated = cursor.rowcount
        conn.commit()
        conn.close()

        if updated > 0:
            logger.info(
                f"✓ Updated {updated} vouches with resolved to_user_id={user_id} for @{norm} (chat_id={chat_id})"
            )
        # Record the username -> user_id mapping so future searches can find this user
        try:
            conn2 = get_db_connection()
            cur2 = conn2.cursor()
            cur2.execute("INSERT INTO username_history (user_id, username_lower) VALUES (?, ?)", (user_id, norm))
            conn2.commit()
            conn2.close()
        except Exception:
            pass
        return updated

    except Exception as e:
        logger.error(f"Failed to update vouches with resolved user id: {e}")
        return 0


def search_vouches(
    query: str,
    chat_id: Optional[int] = None,
    polarity: Optional[str] = None,
    limit: int = 20
) -> List[Dict]:
    """
    Search vouches by username or display name.
    Searches across all fields: from_username, to_username, from_display_name, to_display_name.
    
    Args:
        query: Username or display name to search for (with or without @)
        chat_id: Limit to specific chat (optional)
        polarity: Filter by polarity 'pos' or 'neg' (optional)
        limit: Maximum results to return
    
    Returns:
        List of vouch dictionaries
    """
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        cursor = conn.cursor()
        
        # Clean query (remove @ if present and normalize for indexed search)
        clean_query = query.strip().lstrip('@').lower()
        search_pattern = f"%{clean_query}%"
        
        logger.info(f"Search vouches: query='{query}' -> clean_query='{clean_query}'")
        
        # Build SQL query - search all relevant columns using normalized lowercase columns
        sql = """
            SELECT * FROM vouches 
            WHERE (
                from_username_lower LIKE ? 
                OR to_username_lower LIKE ? 
                OR from_display_name_lower LIKE ? 
                OR to_display_name_lower LIKE ?
            )
        """
        params = [search_pattern, search_pattern, search_pattern, search_pattern]
        
        # Apply optional filters
        if chat_id:
            sql += " AND chat_id = ?"
            params.append(chat_id)
            
        if polarity:
            sql += " AND polarity = ?"
            params.append(polarity)
        
        # Order by timestamp and apply limit
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        logger.info(f"Executing SQL: {sql} with params: {params}")
        cursor.execute(sql, params)
        results = cursor.fetchall()
        conn.close()
        
        logger.info(f"Search query='{query}' returned {len(results)} vouches")
        
        # Convert to list of dicts
        vouches = []
        for row in results:
            vouches.append({
                'id': row['id'],
                'from_user_id': row['from_user_id'],
                'from_username': row['from_username'],
                'from_display_name': row['from_display_name'],
                'to_user_id': row['to_user_id'],
                'to_username': row['to_username'],
                'to_display_name': row['to_display_name'],
                'polarity': row['polarity'],
                'original_text': row['original_text'],
                'canonical_text': row['canonical_text'],
                'chat_id': row['chat_id'],
                'message_id': row['message_id'],
                'created_at': row['created_at'],
                'is_sanitized': bool(row['is_sanitized'])
            })
        
        return vouches
        
    except Exception as e:
        logger.error(f"Failed to search vouches: {e}", exc_info=True)
        return []


def get_vouch_stats(chat_id: Optional[int] = None) -> Dict:
    """
    Get vouch statistics.
    
    Args:
        chat_id: Limit to specific chat (optional)
    
    Returns:
        Dictionary with stats
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Build conditional clause properly
        where_clause = "WHERE chat_id = ?" if chat_id else ""
        and_clause = "AND" if where_clause else "WHERE"
        params = [chat_id] if chat_id else []
        
        # Total vouches
        cursor.execute(f"SELECT COUNT(*) FROM vouches {where_clause}", params)
        total = cursor.fetchone()[0]
        
        # Positive vouches
        pos_params = params + ['pos']
        cursor.execute(f"SELECT COUNT(*) FROM vouches {where_clause} {and_clause} polarity = ?", pos_params)
        positive = cursor.fetchone()[0]
        
        # Negative vouches
        neg_params = params + ['neg']
        cursor.execute(f"SELECT COUNT(*) FROM vouches {where_clause} {and_clause} polarity = ?", neg_params)
        negative = cursor.fetchone()[0]
        
        # Sanitized vouches
        san_params = params + [True]
        cursor.execute(f"SELECT COUNT(*) FROM vouches {where_clause} {and_clause} is_sanitized = ?", san_params)
        sanitized = cursor.fetchone()[0]
        
        # Recent vouches (last 24h) - use numeric timestamp for efficiency
        recent_params = params + []
        cursor.execute(f"""
            SELECT COUNT(*) FROM vouches 
            {where_clause} {and_clause if where_clause else 'WHERE'} 
            timestamp > (strftime('%s','now') - 86400)
        """, recent_params)
        recent = cursor.fetchone()[0]
        
        conn.close()
        
        stats_dict = {
            'total': total,
            'positive': positive,
            'negative': negative,
            'sanitized': sanitized,
            'recent_24h': recent
        }
        logger.debug(f"Vouch stats for chat={chat_id}: {stats_dict}")
        return stats_dict
        
    except Exception as e:
        logger.error(f"Failed to get vouch stats: {e}")
        return {
            'total': 0,
            'positive': 0,
            'negative': 0,
            'sanitized': 0,
            'recent_24h': 0
        }


def get_top_vouchers(
    chat_id: Optional[int] = None,
    days: int = 7,
    limit: int = 10,
    polarity: str = "pos"
) -> List[Dict]:
    """
    Get top vouchers ranked by vouch count in a time window.
    Perfect for leaderboards and competitions.
    
    Args:
        chat_id: Limit to specific chat (optional)
        days: Time window in days (default 7 for weekly competition)
        limit: Max number of top vouchers to return
        polarity: 'pos' for positive vouches, 'neg' for negatives, 'all' for both
    
    Returns:
        List of dicts: [{'from_username': 'alice', 'from_user_id': 123, 'count': 5}, ...]
        Sorted by count descending (highest first)
    """
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Calculate cutoff timestamp (now - N days)
        cutoff_timestamp = datetime.now(UTC).timestamp() - (days * 86400)
        
        # Build parameterized query to prevent SQL injection
        sql = "SELECT from_user_id, from_username, from_display_name, COUNT(*) as vouch_count FROM vouches WHERE timestamp > ?"
        params = [cutoff_timestamp]
        
        if chat_id:
            sql += " AND chat_id = ?"
            params.append(chat_id)
            
        if polarity != "all":
            sql += " AND polarity = ?"
            params.append(polarity)
        
        sql += " GROUP BY from_user_id ORDER BY vouch_count DESC LIMIT ?"
        params.append(limit)
        
        logger.info(f"get_top_vouchers: chat_id={chat_id}, days={days}, polarity={polarity}")
        cursor.execute(sql, params)
        results = cursor.fetchall()
        conn.close()
        logger.info(f"get_top_vouchers returned {len(results)} results")
        
        # Convert to list of dicts
        vouchers = []
        for row in results:
            vouchers.append({
                'from_user_id': row['from_user_id'],
                'from_username': row['from_username'],
                'from_display_name': row['from_display_name'],
                'vouch_count': row['vouch_count']
            })
        
        return vouchers
        
    except Exception as e:
        logger.error(f"Failed to get top vouchers: {e}", exc_info=True)
        return []


def get_recent_vouches(chat_id: Optional[int] = None, limit: int = 20) -> List[Dict]:
    """Return recent vouch rows for a chat (useful for debugging).

    Args:
        chat_id: Chat id to filter. If None, returns recent across all chats.
        limit: Maximum number of rows to return.

    Returns:
        List of rows as dicts
    """
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if chat_id:
            cursor.execute("SELECT * FROM vouches WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?", (chat_id, limit))
        else:
            cursor.execute("SELECT * FROM vouches ORDER BY timestamp DESC LIMIT ?", (limit,))

        rows = cursor.fetchall()
        conn.close()

        vouches = []
        for row in rows:
            vouches.append({
                'id': row['id'],
                'from_user_id': row['from_user_id'],
                'from_username': row['from_username'],
                'to_username': row['to_username'],
                'original_text': row['original_text'],
                'created_at': row['created_at'],
                'is_sanitized': bool(row['is_sanitized']),
            })
        return vouches

    except Exception as e:
        logger.error(f"Failed to get recent vouches for chat={chat_id}: {e}")
        return []


def count_user_vouches(
    user_id: int,
    chat_id: Optional[int] = None,
    days: Optional[int] = None,
    polarity: str = "pos"
) -> int:
    """
    Count how many vouches a specific user has given.
    Great for tracking individual progress in competitions.
    
    Args:
        user_id: User ID to count vouches for
        chat_id: Limit to specific chat (optional)
        days: Limit to last N days (optional, None = all time)
        polarity: 'pos', 'neg', or 'all'
    
    Returns:
        Number of vouches given by the user
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Build WHERE clause
        where_parts = ["from_user_id = ?"]
        params = [user_id]
        
        if chat_id:
            where_parts.append("chat_id = ?")
            params.append(chat_id)
        
        if days is not None:
            cutoff = datetime.now(UTC).timestamp() - (days * 86400)
            where_parts.append(f"timestamp > {cutoff}")
        
        if polarity != "all":
            where_parts.append("polarity = ?")
            params.append(polarity)
        
        where_clause = " AND ".join(where_parts)
        
        cursor.execute(f"SELECT COUNT(*) FROM vouches WHERE {where_clause}", params)
        count = cursor.fetchone()[0]
        conn.close()
        
        logger.debug(f"User {user_id} vouch count: {count} (chat={chat_id}, days={days}, polarity={polarity})")
        return count
        
    except Exception as e:
        logger.error(f"Failed to count user vouches: {e}")
        return 0


def get_last_vouch_timestamp(chat_id: Optional[int] = None) -> Optional[int]:
    """
    Get the timestamp of the most recently stored vouch in the database.
    Useful for syncing/catchup operations.
    
    Args:
        chat_id: Limit to specific chat (optional)
    
    Returns:
        Unix timestamp (seconds) of last vouch, or None if no vouches exist
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if chat_id:
            cursor.execute("SELECT MAX(timestamp) FROM vouches WHERE chat_id = ?", (chat_id,))
        else:
            cursor.execute("SELECT MAX(timestamp) FROM vouches")
        
        result = cursor.fetchone()
        conn.close()
        
        timestamp = result[0] if result and result[0] else None
        logger.debug(f"Last vouch timestamp for chat={chat_id}: {timestamp}")
        return timestamp
        
    except Exception as e:
        logger.error(f"Failed to get last vouch timestamp: {e}")
        return None


def get_last_scanned_message_id(chat_id: int) -> Optional[int]:
    """
    Get the last message ID that was scanned for vouches in a chat.
    Used by sync command to know where to resume scanning.
    
    Args:
        chat_id: Chat ID to get sync state for
    
    Returns:
        Last scanned message ID, or None if no sync history exists
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT last_scanned_message_id FROM sync_state WHERE chat_id = ?", (chat_id,))
        result = cursor.fetchone()
        conn.close()
        
        msg_id = result[0] if result and result[0] else None
        logger.debug(f"Last scanned message ID for chat={chat_id}: {msg_id}")
        return msg_id
        
    except Exception as e:
        logger.error(f"Failed to get last scanned message ID: {e}")
        return None


def update_sync_state(chat_id: int, last_message_id: int, vouches_found: int = 0) -> bool:
    """
    Update the sync state for a chat after scanning.
    Tracks the last scanned message ID and when the sync occurred.
    
    Args:
        chat_id: Chat ID to update
        last_message_id: The message ID that was just scanned
        vouches_found: Number of vouches found in this sync (added to total)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        now = datetime.now(UTC).timestamp()
        
        # Get current total
        cursor.execute("SELECT vouches_found_total FROM sync_state WHERE chat_id = ?", (chat_id,))
        result = cursor.fetchone()
        current_total = (result[0] if result else 0) + vouches_found
        
        # Upsert sync state
        cursor.execute("""
            INSERT INTO sync_state (chat_id, last_scanned_message_id, last_sync_time, vouches_found_total)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                last_scanned_message_id = excluded.last_scanned_message_id,
                last_sync_time = excluded.last_sync_time,
                vouches_found_total = excluded.vouches_found_total
        """, (chat_id, last_message_id, now, current_total))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Updated sync state for chat={chat_id}: last_msg={last_message_id}, total_found={current_total}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to update sync state: {e}")
        return False


def get_sync_stats(chat_id: int) -> Dict:
    """
    Get sync statistics for a chat.
    
    Args:
        chat_id: Chat ID to get stats for
    
    Returns:
        Dict with last_message_id, last_sync_time, total_vouches_found
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT last_scanned_message_id, last_sync_time, vouches_found_total FROM sync_state WHERE chat_id = ?", (chat_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'last_message_id': result[0],
                'last_sync_time': result[1],
                'total_vouches_found': result[2]
            }
        
        return {
            'last_message_id': None,
            'last_sync_time': None,
            'total_vouches_found': 0
        }
        
    except Exception as e:
        logger.error(f"Failed to get sync stats: {e}")
        return {
            'last_message_id': None,
            'last_sync_time': None,
            'total_vouches_found': 0
        }


def format_vouch_for_display(vouch: Dict) -> str:
    """
    Format a vouch dictionary for display in search results.
    
    Args:
        vouch: Vouch dictionary from database
    
    Returns:
        Formatted string for display
    """
    # Determine from/to display text
    from_display = f"@{vouch['from_username']}" if vouch['from_username'] else vouch['from_display_name'] or f"ID:{vouch['from_user_id']}"
    to_display = f"@{vouch['to_username']}" if vouch['to_username'] else vouch['to_display_name'] or f"ID:{vouch['to_user_id']}" if vouch['to_user_id'] else "[unknown]"
    
    # Format timestamp
    created_dt = datetime.fromisoformat(vouch['created_at'].replace('Z', '+00:00')) if 'T' in vouch['created_at'] else datetime.strptime(vouch['created_at'], '%Y-%m-%d %H:%M:%S')
    time_str = created_dt.strftime('%m/%d %H:%M')
    
    # Build display text
    polarity_emoji = "✅" if vouch['polarity'] == 'pos' else "❌"
    sanitized_flag = " 🛡️" if vouch['is_sanitized'] else ""
    
    return f"{polarity_emoji} {from_display} → {to_display} ({time_str}){sanitized_flag}"


# Initialize database on module import (always run to handle migrations)
init_db()
migrate_db()
normalize_existing_vouches()
