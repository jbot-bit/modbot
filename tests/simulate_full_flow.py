"""Simulate full vouch flows: clean vouch, dirty vouch attempts, and retry-window reset.

Run this locally to observe DB state and message actions.
"""
import sys
import os
import asyncio
import logging
import time
from datetime import datetime, timedelta

# Ensure repository root is on sys.path for local imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vouch_db import init_db, get_db_connection, VOUCH_RETRY_WINDOW_SECONDS
from modbot.services import vouches


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class FakeUser:
    def __init__(self, id, username=None, first_name="User"):
        self.id = id
        self.username = username
        self.first_name = first_name


class FakeChat:
    def __init__(self):
        self.sent = []
        self.id = -100123

    async def send_message(self, text, **kwargs):
        msg = type("M", (), {"message_id": len(self.sent) + 100, "text": text})()
        self.sent.append(text)
        logger.debug(f"Chat.send_message: {text}")
        return msg


class FakeMessage:
    def __init__(self, text, user: FakeUser):
        self.text = text
        self.from_user = user
        self.chat = FakeChat()
        self.message_id = int(time.time() % 100000)  # pseudo-unique
        self.chat_id = self.chat.id
        self.deleted = False

    async def delete(self):
        self.deleted = True
        logger.debug(f"Message deleted: {self.text}")


async def _fake_ack(chat, text, reply_to=None, delay=10):
    # record ack synchronously to avoid background delete tasks
    chat.sent.append(f"ACK: {text}")
    logger.debug(f"_send_temp_ack called: {text}")


async def _fake_rewrite(text):
    # simple sanitizer simulation
    return text.replace("banned keyword", "[REMOVED]")


def query_table(conn, table):
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table}")
    rows = cur.fetchall()
    return rows


def print_db_state():
    conn = get_db_connection()
    print("\nVouches table:")
    for row in query_table(conn, "vouches"):
        print(row)
    print("\nRetry attempts table:")
    for row in query_table(conn, "vouch_retry_attempts"):
        print(row)
    conn.close()


async def run_simulation():
    init_db()
    # patch helpers
    vouches._send_temp_ack = _fake_ack
    vouches.rewrite_vouch_with_ai = _fake_rewrite

    # CLEAN vouch: user posts correct vouch -> should be left posted and stored
    user1 = FakeUser(10, username="u1", first_name="User1")
    clean_msg = FakeMessage("vouch @alice reliable seller", user1)
    print("\n--- CLEAN VOUCH: posting by user ---")
    await vouches.handle_clean_vouch(clean_msg, from_username="u1")
    print("Chat messages:", clean_msg.chat.sent)
    print_db_state()

    # DIRTY vouch: three attempts
    user2 = FakeUser(20, username="u2", first_name="User2")
    dirty_text = "vouch @bob sells banned keyword"

    print("\n--- DIRTY VOUCH: Attempt 1 (warning) ---")
    msg1 = FakeMessage(dirty_text, user2)
    await vouches.handle_dirty_vouch(msg1, reason="banned keyword")
    print("Chat messages (attempt1):", msg1.chat.sent)
    print_db_state()

    print("\n--- DIRTY VOUCH: Attempt 2 (final warning) ---")
    msg2 = FakeMessage(dirty_text, user2)
    await vouches.handle_dirty_vouch(msg2, reason="banned keyword")
    print("Chat messages (attempt2):", msg2.chat.sent)
    print_db_state()

    print("\n--- DIRTY VOUCH: Attempt 3 (sanitize & repost) ---")
    msg3 = FakeMessage(dirty_text, user2)
    await vouches.handle_dirty_vouch(msg3, reason="banned keyword")
    print("Chat messages (attempt3):", msg3.chat.sent)
    print_db_state()

    # Simulate retry window expiration: create a fresh retry row then age it
    print("\n--- RETRY WINDOW RESET TEST ---")
    # Trigger one attempt to create row
    msg4 = FakeMessage(dirty_text, user2)
    await vouches.handle_dirty_vouch(msg4, reason="banned keyword")
    conn = get_db_connection()
    cur = conn.cursor()
    # Select the row
    cur.execute("SELECT id, user_id, chat_id, target_username, attempt_count, last_attempt_time FROM vouch_retry_attempts WHERE user_id=?", (user2.id,))
    row = cur.fetchone()
    print("Before aging:", row)
    if row:
        row_id = row[0]
        old_time = row[5]
        # Age it to older than retry window
        aged_time = old_time - (VOUCH_RETRY_WINDOW_SECONDS + 10)
        cur.execute("UPDATE vouch_retry_attempts SET last_attempt_time = ?, attempt_count = ? WHERE id = ?", (aged_time, 3, row_id))
        conn.commit()
        print("Aged row to simulate timeout")
    conn.close()

    # Now next attempt should reset to 1 (we'll call track_vouch_retry_attempt directly)
    from vouch_db import track_vouch_retry_attempt
    reset_count = track_vouch_retry_attempt(user2.id, msg4.chat_id, "@bob")
    print("Counter after aging + new attempt (should be 1):", reset_count)
    print_db_state()


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(run_simulation())
