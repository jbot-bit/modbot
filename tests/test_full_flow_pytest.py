import asyncio
import sys
import os
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vouch_db import init_db, get_db_connection, DB_PATH, VOUCH_RETRY_WINDOW_SECONDS
from modbot.services import vouches
import vouch_db


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
        return msg


class FakeMessage:
    def __init__(self, text, user: FakeUser, chat=None):
        self.text = text
        self.from_user = user
        self.chat = chat or FakeChat()
        self.message_id = int(time.time() % 100000)
        self.chat_id = self.chat.id
        self.deleted = False

    async def delete(self):
        self.deleted = True


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    # Point DB to a temp file for isolation
    db_file = tmp_path / "vouches_test.db"
    monkeypatch.setattr(vouch_db, "DB_PATH", str(db_file))
    init_db()
    yield str(db_file)


@pytest.mark.asyncio
async def test_clean_vouch_stores_original_message(temp_db, monkeypatch):
    # Arrange
    user = FakeUser(1111, username="tester", first_name="Tester")
    msg = FakeMessage("vouch @alice great service", user)

    # Prevent background deletion tasks during test
    async def _fake_ack(chat, text, reply_to=None, delay=10):
        chat.sent.append(text)

    monkeypatch.setattr(vouches, "_send_temp_ack", _fake_ack)

    # Act
    await vouches.handle_clean_vouch(msg, from_username="tester")

    # Assert: a vouch row exists referencing the original message id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT from_user_id, chat_id, message_id, original_text FROM vouches WHERE from_user_id = ?", (user.id,))
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == user.id
    assert row[1] == msg.chat.id
    assert row[2] == msg.message_id


@pytest.mark.asyncio
async def test_dirty_vouch_flow_and_sanitization(temp_db, monkeypatch):
    # Arrange: user and dirty text
    user = FakeUser(2222, username="baduser", first_name="Bad")
    dirty_text = "vouch @bob sells banned keyword"

    # Patch ack and rewrite
    async def _fake_ack(chat, text, reply_to=None, delay=10):
        chat.sent.append(text)

    async def _fake_rewrite(text):
        return text.replace("banned keyword", "[REMOVED]")

    monkeypatch.setattr(vouches, "_send_temp_ack", _fake_ack)
    monkeypatch.setattr(vouches, "rewrite_vouch_with_ai", _fake_rewrite)

    # Attempt 1
    msg1 = FakeMessage(dirty_text, user)
    await vouches.handle_dirty_vouch(msg1, reason="banned keyword")
    # Attempt 2
    msg2 = FakeMessage(dirty_text, user)
    await vouches.handle_dirty_vouch(msg2, reason="banned keyword")
    # Attempt 3 -> there is no retry/sanitization; the message is deleted and a warning is posted
    msg3 = FakeMessage(dirty_text, user)
    await vouches.handle_dirty_vouch(msg3, reason="banned keyword")

    # Assert: no sanitized vouch present in DB (we don't auto-repost/sanitize anymore)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT is_sanitized, canonical_text FROM vouches WHERE from_user_id = ? ORDER BY id DESC LIMIT 1", (user.id,))
    row = cur.fetchone()
    conn.close()

    assert row is None


def test_retry_window_reset(temp_db):
    # Arrange
    user_id = 9999
    chat_id = -100123
    target = "@charlie"

    # Create initial attempts
    from vouch_db import track_vouch_retry_attempt, get_db_connection
    first = track_vouch_retry_attempt(user_id, chat_id, target)
    second = track_vouch_retry_attempt(user_id, chat_id, target)
    assert second == first + 1

    # Age the row beyond the retry window
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, last_attempt_time FROM vouch_retry_attempts WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    assert row is not None
    row_id = row[0]
    old_time = row[1]
    aged_time = old_time - (VOUCH_RETRY_WINDOW_SECONDS + 5)
    cur.execute("UPDATE vouch_retry_attempts SET last_attempt_time = ?, attempt_count = ? WHERE id = ?", (aged_time, 3, row_id))
    conn.commit()
    conn.close()

    # Next attempt should reset to 1
    count_after = track_vouch_retry_attempt(user_id, chat_id, target)
    assert count_after == 1
