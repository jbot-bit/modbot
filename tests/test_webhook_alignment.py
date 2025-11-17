import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_base_webhook_url, get_final_webhook_url, BOT_TOKEN


def test_webhook_alignment_default_base(monkeypatch):
    monkeypatch.setenv("WEBHOOK_URL", "https://seqmodbot.replit.app/webhook")
    res = get_final_webhook_url()
    assert res.endswith(BOT_TOKEN) or BOT_TOKEN is None


def test_webhook_alignment_custom(monkeypatch):
    # When base is host-only, token should be appended
    monkeypatch.setenv("WEBHOOK_URL", "https://seqmodbot.replit.app")
    res = get_final_webhook_url()
    assert res.endswith(BOT_TOKEN) if BOT_TOKEN else True


def test_webhook_alignment_token_present(monkeypatch):
    # If WEBHOOK_URL already includes token, it should not be appended again
    monkeypatch.setenv("WEBHOOK_URL", f"https://seqmodbot.replit.app/{BOT_TOKEN}")
    res = get_final_webhook_url()
    assert res.count(BOT_TOKEN) == 1
