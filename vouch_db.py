"""
Vouch Database Module
Stores canonical vouches in SQLite for persistence and searchability.
Handles cases where user accounts are deleted but vouches remain searchable.
"""
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional
import os

logger = logging.getLogger(__name__)

DB_PATH = "vouches.db"


def get_db_connection():
    """Get a database connection with WAL mode and concurrent access optimizations."""
    conn = sqlite3.connect(DB_PATH)
    # Enable WAL mode for concurrent reads/writes
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA timeout=5000")  # 5 second timeout for locked DB
    return conn


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
        cursor.execute("""
            SELECT COUNT(*) FROM vouches 
            WHERE from_user_id = ? 
              AND to_username_lower = ?
              AND polarity = ?
              AND created_at > datetime('now', '-1 day')
        """, (from_user_id, to_username.lower() if to_username else None, polarity))
        
        result = cursor.fetchone()[0] > 0
        conn.close()
        
        if result:
            logger.debug(f"24h vouch duplicate detected: user={from_user_id}, target={to_username}, polarity={polarity}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to check vouch duplicate: {e}")
        return False  # On error, allow vouch (fail-open)


def get_prior_vouchers_for_target(to_username: Optional[str], polarity: str = "pos", limit: int = 5) -> List[Dict]:
    if not to_username:
        return []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT from_user_id, from_username, from_display_name
            FROM vouches
            WHERE to_username_lower = ?
              AND polarity = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (to_username.lower(), polarity, limit),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "from_user_id": row[0],
                "from_username": row[1],
                "from_display_name": row[2],
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Failed to fetch prior vouchers: {e}")
        return []


def init_database():
    """Initialize the vouches database with required tables."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.isolation_level = None  # Autocommit mode for initialization
        
        # Enable WAL mode for better concurrent access
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")  # Good balance of safety/speed
        conn.execute("PRAGMA query_only=FALSE")
        
        cursor = conn.cursor()
        
        # Create vouches table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vouches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER NOT NULL,
                from_username TEXT,
                from_display_name TEXT,
                to_user_id INTEGER,
                to_username TEXT,
                to_display_name TEXT,
                polarity TEXT NOT NULL CHECK (polarity IN ('pos', 'neg')),
                original_text TEXT,
                canonical_text TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_sanitized BOOLEAN DEFAULT FALSE,
                from_username_lower TEXT,
                to_username_lower TEXT,
                from_display_name_lower TEXT,
                to_display_name_lower TEXT
            )
        """)
        
        # Create indexes for search performance
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_from_username_lower ON vouches(from_username_lower)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_to_username_lower ON vouches(to_username_lower)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_from_display_name_lower ON vouches(from_display_name_lower)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_to_display_name_lower ON vouches(to_display_name_lower)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_id ON vouches(chat_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_polarity ON vouches(polarity)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_is_sanitized ON vouches(is_sanitized)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON vouches(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_message ON vouches(chat_id, message_id)")
        except Exception as idx_err:
            logger.warning(f"Could not create indexes: {idx_err}")
        
        # Migration: Add normalized columns if they don't exist
        columns_added = False
        try:
            cursor.execute("ALTER TABLE vouches ADD COLUMN from_username_lower TEXT")
            columns_added = True
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE vouches ADD COLUMN to_username_lower TEXT")
            columns_added = True
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE vouches ADD COLUMN from_display_name_lower TEXT")
            columns_added = True
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE vouches ADD COLUMN to_display_name_lower TEXT")
            columns_added = True
        except sqlite3.OperationalError:
            pass
        
        # Backfill normalized columns for existing rows
        if columns_added:
            cursor.execute("""
                UPDATE vouches 
                SET from_username_lower = LOWER(from_username),
                    to_username_lower = LOWER(to_username),
                    from_display_name_lower = LOWER(from_display_name),
                    to_display_name_lower = LOWER(to_display_name)
                WHERE from_username_lower IS NULL 
                   OR to_username_lower IS NULL 
                   OR from_display_name_lower IS NULL 
                   OR to_display_name_lower IS NULL
            """)
            logger.info("✓ Backfilled normalized columns for existing vouches")
        
        # Create indexes for fast searching - use normalized columns
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_from_username_lower ON vouches(from_username_lower)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_to_username_lower ON vouches(to_username_lower)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_from_display_name_lower ON vouches(from_display_name_lower)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_to_display_name_lower ON vouches(to_display_name_lower)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_from_user_id ON vouches(from_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_to_user_id ON vouches(to_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_id ON vouches(chat_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON vouches(created_at)")
        
        conn.commit()
        conn.close()
        logger.info("✓ Vouch database initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize vouch database: {e}")


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
        
        # Prevent duplicates: check if exact same vouch already exists (same chat, user, original_text)
        # This handles offline recovery where same message might be processed twice
        cursor.execute("""
            SELECT COUNT(*) FROM vouches 
            WHERE chat_id = ? AND from_user_id = ? AND original_text = ?
        """, (chat_id, from_user_id, original_text))
        
        if cursor.fetchone()[0] > 0:
            logger.debug(f"Duplicate vouch detected - skipping: chat={chat_id}, user={from_user_id}")
            conn.close()
            return False  # Already stored
        
        # Normalize text for fast case-insensitive searching
        from_username_lower = from_username.lower() if from_username else None
        to_username_lower = to_username.lower() if to_username else None
        from_display_name_lower = from_display_name.lower() if from_display_name else None
        to_display_name_lower = to_display_name.lower() if to_display_name else None
        
        cursor.execute("""
            INSERT INTO vouches (
                from_user_id, from_username, from_display_name,
                to_user_id, to_username, to_display_name,
                polarity, original_text, canonical_text,
                chat_id, message_id, is_sanitized,
                from_username_lower, to_username_lower,
                from_display_name_lower, to_display_name_lower
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            from_user_id, from_username, from_display_name,
            to_user_id, to_username, to_display_name,
            polarity, original_text, canonical_text,
            chat_id, message_id, is_sanitized,
            from_username_lower, to_username_lower,
            from_display_name_lower, to_display_name_lower
        ))
        
        conn.commit()
        conn.close()
        
        logger.info(f"✓ Stored vouch: {from_username or from_user_id} -> {to_username or to_user_id} ({polarity})")
        return True
        
    except Exception as e:
        logger.error(f"Failed to store vouch: {e}")
        return False


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
        cursor.execute("""
            UPDATE vouches 
            SET message_id = ? 
            WHERE chat_id = ? AND message_id = 0
            ORDER BY created_at DESC
            LIMIT 1
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


def search_vouches(
    query: str,
    chat_id: Optional[int] = None,
    polarity: Optional[str] = None,
    limit: int = 20
) -> List[Dict]:
    """
    Search vouches by username or display name.
    
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
        clean_query = query.lstrip('@').lower()
        
        # Build SQL query - use normalized columns for index efficiency
        sql = """
            SELECT * FROM vouches 
            WHERE (
                from_username_lower LIKE ? OR 
                to_username_lower LIKE ? OR
                from_display_name_lower LIKE ? OR
                to_display_name_lower LIKE ?
            )
        """
        params = [f"%{clean_query}%"] * 4
        
        if chat_id:
            sql += " AND chat_id = ?"
            params.append(chat_id)
            
        if polarity:
            sql += " AND polarity = ?"
            params.append(polarity)
            
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(sql, params)
        results = cursor.fetchall()
        conn.close()
        
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
        logger.error(f"Failed to search vouches: {e}")
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
        
        # Recent vouches (last 24h)
        recent_params = params + []
        cursor.execute(f"""
            SELECT COUNT(*) FROM vouches 
            {where_clause} {and_clause if where_clause else 'WHERE'} 
            created_at > datetime('now', '-1 day')
        """, recent_params)
        recent = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'total': total,
            'positive': positive,
            'negative': negative,
            'sanitized': sanitized,
            'recent_24h': recent
        }
        
    except Exception as e:
        logger.error(f"Failed to get vouch stats: {e}")
        return {
            'total': 0,
            'positive': 0,
            'negative': 0,
            'sanitized': 0,
            'recent_24h': 0
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
init_database()
