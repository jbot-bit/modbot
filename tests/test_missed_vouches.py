import asyncio
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modbot.handlers.commands import handle_missed_vouches
from vouch_db import get_db_connection


class DummyUpdate:
    def __init__(self, message):
        self.message = message
        self.update_id = 99999


class DummyBot:
    def __init__(self, updates):
        self._updates = updates

    async def get_updates(self, offset=None):
        # return list of DummyUpdate
        return self._updates


class DummyContext:
    def __init__(self, bot):
        self.bot = bot


class FakeUser:
    def __init__(self, id, username=None):
        self.id = id
        self.username = username


class FakeMessage:
    def __init__(self, text, from_user, chat_id=-100123, message_id=111):
        self.text = text
        self.from_user = from_user
        self.chat_id = chat_id
        self.chat = type('C', (), {'id': chat_id})()
        self.message_id = message_id
        self.date = datetime.now(timezone.utc)  # Updated to use timezone-aware datetime


def run(coro):
    loop = asyncio.new_event_loop()  # Updated to create a new event loop
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def test_missed_vouches_stored(monkeypatch):
    # create fake message and update
    user = FakeUser(8888, username='missedtest')
    msg = FakeMessage('vouch @alice fabulous', user)
    update = DummyUpdate(msg)
    bot = DummyBot([update])
    ctx = DummyContext(bot)

    # Ensure DB has no existing rows for message
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM vouches WHERE chat_id = ? AND message_id = ?', (msg.chat_id, msg.message_id))
    conn.commit()
    conn.close()

    # Prevent duplicate blocking and bypass moderation checks for the test
    from modbot.services import vouches
    import moderation_engine.engine as me
    monkeypatch.setattr(vouches, "check_vouch_duplicate_24h", lambda *a, **k: False)
    monkeypatch.setattr(vouches, "_send_temp_ack", lambda *a, **k: None)
    # Force is_vouch to true so we always call vouches code
    monkeypatch.setattr(me, "is_vouch", lambda t: True)

    # Spy on handle_clean_vouch to see it was called
    from modbot.services import vouches as vservices

    called = {"yes": False}

    async def fake_handle_clean_vouch(message, from_username=None):
        called["yes"] = True
        # call the real store directly to mimic behavior
        from vouch_db import store_vouch
        store_vouch(
            from_user_id=message.from_user.id,
            from_username=message.from_user.username,
            from_display_name=message.from_user.username,
            to_user_id=None,
            to_username="alice",
            to_display_name=None,
            polarity="pos",
            original_text=message.text,
            canonical_text=message.text.lower(),
            chat_id=message.chat.id,
            message_id=message.message_id,
            is_sanitized=False,
        )

    monkeypatch.setattr(vservices, "handle_clean_vouch", fake_handle_clean_vouch)

    # Run
    run(handle_missed_vouches(ctx))

    # Verify stored
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT to_username FROM vouches WHERE chat_id = ? AND message_id = ?', (msg.chat_id, msg.message_id))
    rows = cur.fetchall()
    conn.close()

    assert called["yes"], "handle_clean_vouch wasn't called by missed_vouches"
    assert rows and len(rows) >= 1
