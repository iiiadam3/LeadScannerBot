"""
Tests for the Telegram bot helpers. No network and no database: every test
calls a plain function or a stubbed one.
"""
import importlib
import os
import sys

import pytest

# bot_manager refuses to load without a token, so give it a well-formed fake one.
os.environ.setdefault("TELEGRAM_TOKEN", "123456:TEST-TOKEN")

import bot_manager  # noqa: E402


# ---------------------------------------------------------------------------
# Markdown escaping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("word", ["node_js", "my*service", "[design]", "a_b*c`d["])
def test_formatting_characters_are_escaped(word):
    """Left as typed, these make Telegram reject the whole message with a 400."""
    escaped = bot_manager.escape_markdown(word)
    for position, character in enumerate(escaped):
        if character in "_*`[":
            assert position > 0 and escaped[position - 1] == "\\"


@pytest.mark.parametrize("word", ["seo", "C++", "עיצוב לוגו", "react native"])
def test_ordinary_words_are_left_alone(word):
    assert bot_manager.escape_markdown(word) == word


# ---------------------------------------------------------------------------
# Button ids: Telegram rejects callback_data over 64 bytes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("word", [
    "seo",
    "עיצוב גרפי",
    "פיתוח אפליקציות מובייל לאנדרואיד ואייפון",   # 84 bytes as raw text
    "x" * 200,
])
def test_button_data_always_fits_telegrams_limit(word):
    data = bot_manager.DELETE_PREFIX + bot_manager.service_token(word)
    assert len(data.encode("utf-8")) <= 64


def test_same_word_always_gives_the_same_id():
    assert bot_manager.service_token("עיצוב לוגו") == bot_manager.service_token("עיצוב לוגו")


def test_different_words_give_different_ids():
    words = ["seo", "עיצוב לוגו", "react", "react native"]
    assert len({bot_manager.service_token(w) for w in words}) == len(words)


# ---------------------------------------------------------------------------
# Webhook registration
# ---------------------------------------------------------------------------
def test_webhook_url_joins_base_and_token():
    assert bot_manager.webhook_url("https://app.onrender.com") == (
        "https://app.onrender.com/" + bot_manager.TELEGRAM_TOKEN)


def test_webhook_url_tolerates_a_trailing_slash():
    assert (bot_manager.webhook_url("https://app.onrender.com/")
            == bot_manager.webhook_url("https://app.onrender.com"))


def test_webhook_is_registered_with_the_address_telegram_should_post_to(monkeypatch):
    registered = {}
    monkeypatch.setattr(bot_manager.bot, "remove_webhook", lambda: None)
    monkeypatch.setattr(bot_manager.bot, "set_webhook", lambda url: registered.update(url=url))

    assert bot_manager.configure_webhook("https://app.onrender.com") is True
    assert registered["url"] == bot_manager.webhook_url("https://app.onrender.com")


def test_render_supplies_the_address_automatically(monkeypatch):
    registered = {}
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://auto.onrender.com")
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    monkeypatch.setattr(bot_manager.bot, "remove_webhook", lambda: None)
    monkeypatch.setattr(bot_manager.bot, "set_webhook", lambda url: registered.update(url=url))

    assert bot_manager.configure_webhook() is True
    assert registered["url"].startswith("https://auto.onrender.com/")


def test_explicit_webhook_url_wins_over_renders(monkeypatch):
    registered = {}
    monkeypatch.setenv("WEBHOOK_URL", "https://chosen.example.com")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://auto.onrender.com")
    monkeypatch.setattr(bot_manager.bot, "remove_webhook", lambda: None)
    monkeypatch.setattr(bot_manager.bot, "set_webhook", lambda url: registered.update(url=url))

    bot_manager.configure_webhook()
    assert registered["url"].startswith("https://chosen.example.com/")


def test_without_an_address_it_reports_failure_instead_of_crashing(monkeypatch):
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    assert bot_manager.configure_webhook() is False


def test_a_telegram_outage_does_not_stop_the_service_starting(monkeypatch):
    def explode(*args, **kwargs):
        raise ConnectionError("Telegram unreachable")

    monkeypatch.setattr(bot_manager.bot, "remove_webhook", explode)
    assert bot_manager.configure_webhook("https://app.onrender.com") is False


# ---------------------------------------------------------------------------
# Missing configuration
# ---------------------------------------------------------------------------
def test_a_missing_token_says_so_in_plain_words(monkeypatch):
    """It used to fail with "'NoneType' object is not iterable", which named nothing."""
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    sys.modules.pop("bot_manager", None)
    try:
        with pytest.raises(RuntimeError, match="TELEGRAM_TOKEN"):
            importlib.import_module("bot_manager")
    finally:
        sys.modules.pop("bot_manager", None)
