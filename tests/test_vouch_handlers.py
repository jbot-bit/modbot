import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modbot.services import vouches


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
        # Return a simple object with message_id
        msg = type("M", (), {"message_id": len(self.sent) + 100, "text": text})()
        self.sent.append(text)
        return msg


class FakeMessage:
    def __init__(self, text, user: FakeUser):
        self.text = text
        self.from_user = user
        self.chat = FakeChat()
        self.message_id = 12345
        self.chat_id = self.chat.id
        self.deleted = False

    async def delete(self):
        self.deleted = True


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_handle_clean_vouch_stores_original_message(monkeypatch):
    user = FakeUser(1111, username="tester", first_name="Tester")
    msg = FakeMessage("vouch @alice great service", user)

    stored = {}

    def fake_store_vouch(**kwargs):
        stored.update(kwargs)
        return True

    # Prevent background delete tasks by mocking the temp ack to a simple async fn
    async def _fake_ack(chat, text, reply_to=None, delay=10):
        chat.sent.append(text)

    # Make duplicate check return False so it stores
    monkeypatch.setattr(vouches, "_send_temp_ack", _fake_ack)
    monkeypatch.setattr(vouches, "check_vouch_duplicate_24h", lambda *a, **k: False)
    monkeypatch.setattr(vouches, "store_vouch", fake_store_vouch)

    run(vouches.handle_clean_vouch(msg, from_username="tester"))

    assert stored, "store_vouch was not called"
    # message_id should be the original message id (we left user message posted)
    assert stored.get("message_id") == msg.message_id
    assert stored.get("from_user_id") == user.id


def test_handle_clean_vouch_multiple_targets(monkeypatch):
    """A single vouch message mentioning multiple users should store separate vouches for each target."""
    user = FakeUser(3333, username="multi", first_name="Multi")
    msg = FakeMessage("vouch @alice @bob great service", user)

    stored_calls = []

    def fake_store_vouch(**kwargs):
        stored_calls.append(kwargs)
        return True

    async def _fake_ack(chat, text, reply_to=None, delay=10):
        chat.sent.append(text)

    monkeypatch.setattr(vouches, "_send_temp_ack", _fake_ack)
    monkeypatch.setattr(vouches, "check_vouch_duplicate_24h", lambda *a, **k: False)
    monkeypatch.setattr(vouches, "store_vouch", fake_store_vouch)

    run(vouches.handle_clean_vouch(msg, from_username="multi"))

    assert len(stored_calls) == 2, f"Expected 2 stored vouches, got {len(stored_calls)}"
    targets = {c.get("to_username") for c in stored_calls}
    assert "alice" in targets and "bob" in targets


def test_handle_clean_vouch_inserts_db_multiple_targets(monkeypatch):
    """Integration-like test: ensure store_vouch actually writes separate entries for multiple targets."""
    from vouch_db import get_db_connection

    user = FakeUser(4444, username="dbtester", first_name="DBTest")
    msg = FakeMessage("vouch @alice @bob great service", user)

    # Prevent temporary ack from attempting to delete message
    async def _fake_ack(chat, text, reply_to=None, delay=10):
        chat.sent.append(text)

    monkeypatch.setattr(vouches, "_send_temp_ack", _fake_ack)
    monkeypatch.setattr(vouches, "check_vouch_duplicate_24h", lambda *a, **k: False)

    # Run the handler which uses the real `store_vouch`
    run(vouches.handle_clean_vouch(msg, from_username="dbtester"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT to_username FROM vouches WHERE chat_id = ? AND message_id = ?", (msg.chat_id, msg.message_id))
    rows = cur.fetchall()
    # Clean up inserted rows after test
    cur.execute("DELETE FROM vouches WHERE chat_id = ? AND message_id = ?", (msg.chat_id, msg.message_id))
    conn.commit()
    conn.close()

    assert len(rows) >= 2, f"Expected multiple vouches stored for one message, found {len(rows)}"


def test_search_returns_targets(monkeypatch):
    from vouch_db import get_db_connection, search_vouches

    user = FakeUser(5555, username="searcher", first_name="Search")
    msg = FakeMessage("vouch @charlie great", user)

    async def _fake_ack(chat, text, reply_to=None, delay=10):
        chat.sent.append(text)

    monkeypatch.setattr(vouches, "_send_temp_ack", _fake_ack)
    monkeypatch.setattr(vouches, "check_vouch_duplicate_24h", lambda *a, **k: False)

    # Add vouch via handler
    run(vouches.handle_clean_vouch(msg, from_username="searcher"))

    # Search for 'charlie'
    res = search_vouches("@charlie")
    assert any("charlie" in (v.get("to_username") or "") for v in res), "Search didn't return expected target"

    # Cleanup
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM vouches WHERE chat_id = ? AND message_id = ?", (msg.chat_id, msg.message_id))
    conn.commit()
    conn.close()


def test_handle_dirty_vouch_attempts(monkeypatch):
    user = FakeUser(2222, username="baduser", first_name="Bad")
    orig_text = "vouch @bob sells banned keyword"
    msg = FakeMessage(orig_text, user)

    calls = {"store": [], "clear": False}

    async def fake_rewrite(text):
        return "vouch @bob professional service"

    def fake_store_vouch(**kwargs):
        calls["store"].append(kwargs)
        return True

    def fake_clear(uid, cid, target):
        calls["clear"] = True

    # Prevent background delete tasks by mocking the temp ack to a simple async fn
    async def _fake_ack(chat, text, reply_to=None, delay=10):
        chat.sent.append(text)

    # Patch moderation rewrite
    monkeypatch.setattr(vouches, "_send_temp_ack", _fake_ack)
    monkeypatch.setattr(vouches, "rewrite_vouch_with_ai", fake_rewrite)
    monkeypatch.setattr(vouches, "store_vouch", fake_store_vouch)
    # No retry counter support in service layer — we simply delete and warn
    # monkeypatch.setattr(vouches, "clear_vouch_retry_attempts", fake_clear)

    # Case: attempt 1 -> should send warning, not store
    run(vouches.handle_dirty_vouch(msg, reason="banned keyword detected"))
    assert any("Vouch Rejected" in s or "Vouch Rejected" in s for s in msg.chat.sent), "Attempt 1 warning not sent"
    assert not calls["store"], "store_vouch should not be called on attempt 1"

    # Case: attempt 2 -> still a warning, no storage
    msg2 = FakeMessage(orig_text, user)
    run(vouches.handle_dirty_vouch(msg2, reason="banned keyword detected"))
    # We no longer implement a 'final warning' — deletion + notice is sufficient
    assert any("Vouch Rejected" in s for s in msg2.chat.sent), "Attempt 2 warning not sent"
    assert not calls["store"], "store_vouch should not be called on attempt 2"

    # Case: attempt 3 -> our service does not implement retry logic; just delete
    msg3 = FakeMessage(orig_text, user)
    run(vouches.handle_dirty_vouch(msg3, reason="banned keyword detected"))
    # No sanitized repost; should not have stored
    assert not calls["store"], "store_vouch should not be called (no retry/sanitization)"
    # And clear should not be called
    assert not calls["clear"], "clear_vouch_retry_attempts should not be used"


def test_handle_clean_vouch_text_mention_resolves_user_id(monkeypatch):
    from types import SimpleNamespace

    # Prepare a fake message with a text_mention entity pointing to a user id
    user = FakeUser(6666, username="mentioner", first_name="Mentioner")
    msg = FakeMessage("vouch @target great", user)
    # Create a fake entity that simulates MessageEntity(TEXT_MENTION)
    ent_user = SimpleNamespace(id=9999, username="target", first_name="Target")
    text_mention = SimpleNamespace(type='text_mention', offset=6, length=7, user=ent_user)
    msg.entities = [text_mention]

    stored = {}

    def fake_store_vouch(**kwargs):
        stored.update(kwargs)
        return True

    async def _fake_ack(chat, text, reply_to=None, delay=10):
        chat.sent.append(text)

    monkeypatch.setattr(vouches, "_send_temp_ack", _fake_ack)
    monkeypatch.setattr(vouches, "check_vouch_duplicate_24h", lambda *a, **k: False)
    monkeypatch.setattr(vouches, "store_vouch", fake_store_vouch)

    run(vouches.handle_clean_vouch(msg, from_username="mentioner"))

    assert stored, "store_vouch not called"
    assert stored.get("to_user_id") == 9999


def test_username_history_resolves_old_vouches(monkeypatch):
    """Username history should allow searches by the user's new username after mapping"""
    from vouch_db import get_db_connection, update_vouches_with_resolved_user_id, search_vouches

    conn = get_db_connection()
    cur = conn.cursor()

    # Insert an old vouch that referenced 'oldname' and has no to_user_id.
    cur.execute(
        "INSERT INTO vouches (from_user_id, from_username, to_username, polarity, original_text, canonical_text, chat_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (2020, 'tester', 'oldname', 'pos', 'vouch @oldname', '@tester\npos vouch for\n@oldname', -98765),
    )
    conn.commit()

    # Now we discover that oldname belongs to user 321
    updated = update_vouches_with_resolved_user_id(-98765, 'oldname', 321)
    assert updated >= 1

    # User later changes to newname; record mapping for newname -> same user id
    update_vouches_with_resolved_user_id(None, 'newname', 321)

    # Searching by newname should find the vouch via to_user_id mapping
    results = search_vouches('@newname', chat_id=-98765)
    assert any(v['to_user_id'] == 321 for v in results), "Search by new username did not return vouches for user id"

    # Cleanup
    cur.execute("DELETE FROM vouches WHERE chat_id = ?", (-98765,))
    cur.execute("DELETE FROM username_history WHERE user_id = ?", (321,))
    conn.commit()
    conn.close()


def test_update_vouches_with_resolved_user_id():
    """Ensure DB rows that targeted a username without a user_id get updated when we learn the user id."""
    from vouch_db import get_db_connection, update_vouches_with_resolved_user_id

    conn = get_db_connection()
    cur = conn.cursor()
    # Insert a placeholder vouch that has to_user_id NULL
    cur.execute(
        "INSERT INTO vouches (from_user_id, from_username, to_username, polarity, original_text, canonical_text, chat_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1010, 'tester', 'targetuser', 'pos', 'vouch @targetuser', '@tester\npos vouch for\n@targetuser', -12345),
    )
    conn.commit()

    # Now resolve username to a user_id
    updated = update_vouches_with_resolved_user_id(-12345, 'targetuser', 8888)
    assert updated >= 1

    # Verify DB
    cur.execute("SELECT to_user_id FROM vouches WHERE to_username_lower = ? AND chat_id = ?", ('targetuser', -12345))
    rows = cur.fetchall()
    assert all(r[0] == 8888 for r in rows)

    # Cleanup
    cur.execute("DELETE FROM vouches WHERE chat_id = ?", (-12345,))
    conn.commit()
    conn.close()


def _simple_monkeypatch():
    class MP:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)
    return MP()


if __name__ == "__main__":
    print("Running vouch handler unit tests...")
    mp = _simple_monkeypatch()
    test_handle_clean_vouch_stores_original_message(mp)
    test_handle_dirty_vouch_attempts(mp)
    print("All vouch handler tests passed")
