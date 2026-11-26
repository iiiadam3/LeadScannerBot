import requests
from unittest.mock import patch, MagicMock
from LeadScanner import compile_keyword_pattern, get_ai_score


def test_compile_keyword_pattern_whole_word_matching():
    pattern = compile_keyword_pattern(["ai", "c++", "python"])
    assert pattern is not None

    # Exact whole-word matches should succeed
    assert pattern.search("Looking for an AI developer") is not None
    assert pattern.search("Need help with C++ project") is not None

    # Substring inside another word ("ai" inside "said" or "email") must NOT match
    assert pattern.search("He said he will send an email") is None


def test_compile_keyword_pattern_empty_list():
    assert compile_keyword_pattern([]) is None


@patch("LeadScanner.requests.post")
@patch("LeadScanner.OPENAI_API_KEY", "test-api-key")
def test_get_ai_score_valid_response(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "8"}}]
    }
    mock_post.return_value = mock_response

    score = get_ai_score("Hiring Python Dev", "Budget is $500 for a Flask API")
    assert score == 8


@patch("LeadScanner.requests.post")
@patch("LeadScanner.OPENAI_API_KEY", "test-api-key")
def test_get_ai_score_returns_none_on_api_error(mock_post):
    mock_post.side_effect = requests.RequestException("OpenAI timeout")

    score = get_ai_score("Hiring Python Dev", "Need a quick script")
    assert score is None


@patch("LeadScanner.requests.post")
@patch("LeadScanner.OPENAI_API_KEY", "test-api-key")
def test_get_ai_score_returns_none_on_out_of_range_score(mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "15"}}]
    }
    mock_post.return_value = mock_response

    score = get_ai_score("Hiring Python Dev", "Need a quick script")
    assert score is None

# ==========================================
# --- process_entry ---
# ==========================================
import psycopg2
import pytest
from LeadScanner import process_entry

TOKEN = "fake-telegram-token"

HOT_ENTRY = {
    "title": "Hiring a Python developer",
    "summary": "Budget is $500 for a Flask API",
    "link": "https://example.com/jobs/abc",
    "published": "Mon, 01 Jan 2026",
}


def make_conn(rowcount=1, execute_side_effect=None):
    """A fake psycopg2 connection whose cursor() works as a context manager."""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.rowcount = rowcount
    if execute_side_effect is not None:
        cur.execute.side_effect = execute_side_effect
    return conn, cur


def make_patterns(**users):
    """make_patterns(u1=["python"]) -> {"u1": <compiled regex>}"""
    return {cid: compile_keyword_pattern(words) for cid, words in users.items()}


@pytest.fixture
def ai():
    with patch("LeadScanner.get_ai_score", return_value=8) as m:
        yield m


@pytest.fixture
def notify():
    with patch("LeadScanner.send_telegram_notification") as m:
        yield m


def run(conn, entry, patterns):
    process_entry(conn, entry, "TestSource", {}, patterns, TOKEN)


@pytest.mark.parametrize("entry", [
    pytest.param({**HOT_ENTRY, "link": ""}, id="missing-link"),
    pytest.param({**HOT_ENTRY, "title": "Python developer", "summary": "Flask API"},
                 id="no-intent-word"),
    pytest.param({**HOT_ENTRY, "summary": "Python tutorial, budget $500"},
                 id="negative-word"),
])
def test_filtered_out_before_ai_and_db(entry, ai, notify):
    conn, _ = make_conn()
    run(conn, entry, make_patterns(u1=["python"]))

    ai.assert_not_called()
    conn.cursor.assert_not_called()
    notify.assert_not_called()


def test_no_matching_user_skips_ai(ai, notify):
    conn, _ = make_conn()
    run(conn, HOT_ENTRY, make_patterns(u1=["shopify"]))

    ai.assert_not_called()
    conn.cursor.assert_not_called()


def test_ai_called_once_for_multiple_matching_users(ai, notify):
    conn, cur = make_conn()
    run(conn, HOT_ENTRY, make_patterns(u1=["python"], u2=["flask"], u3=["shopify"]))

    ai.assert_called_once_with(HOT_ENTRY["title"], HOT_ENTRY["summary"])
    assert cur.execute.call_count == 2
    saved_for = [c.args[1][5] for c in cur.execute.call_args_list]
    assert saved_for == ["u1", "u2"]
    assert [c.args[1] for c in notify.call_args_list] == ["u1", "u2"]


def test_saved_row_contents(ai, notify):
    conn, cur = make_conn()
    run(conn, HOT_ENTRY, make_patterns(u1=["python"]))

    params = cur.execute.call_args.args[1]
    assert params == (HOT_ENTRY["published"], HOT_ENTRY["title"],
                      HOT_ENTRY["link"], 0, 8, "u1")
    conn.commit.assert_called_once()


def test_ai_failure_skips_save_and_notification(ai, notify):
    ai.return_value = None
    conn, _ = make_conn()
    run(conn, HOT_ENTRY, make_patterns(u1=["python"], u2=["flask"]))

    ai.assert_called_once()  # not retried per user
    conn.cursor.assert_not_called()
    notify.assert_not_called()


@pytest.mark.parametrize("score, should_notify", [(6, False), (7, True), (10, True)])
def test_notification_threshold(score, should_notify, ai, notify):
    ai.return_value = score
    conn, _ = make_conn()
    run(conn, HOT_ENTRY, make_patterns(u1=["python"]))

    assert notify.called is should_notify
    if should_notify:
        token, chat_id, title, link, _, source = notify.call_args.args
        assert (token, chat_id, link, source) == (TOKEN, "u1", HOT_ENTRY["link"], "TestSource")
        assert str(score) in title


def test_duplicate_lead_is_not_notified_again(ai, notify):
    conn, _ = make_conn(rowcount=0)  # ON CONFLICT DO NOTHING hit
    run(conn, HOT_ENTRY, make_patterns(u1=["python"]))

    notify.assert_not_called()


def test_db_error_for_one_user_does_not_block_others(ai, notify):
    conn, cur = make_conn(execute_side_effect=[psycopg2.Error("boom"), None])
    run(conn, HOT_ENTRY, make_patterns(u1=["python"], u2=["flask"]))

    conn.rollback.assert_called_once()
    assert [c.args[1] for c in notify.call_args_list] == ["u2"]


def test_ai_disabled_score_zero_saves_but_never_notifies(ai, notify):
    """Documents current behaviour: without OPENAI_API_KEY get_ai_score returns 0,
    so leads are stored but no user is ever notified."""
    ai.return_value = 0
    conn, cur = make_conn()
    run(conn, HOT_ENTRY, make_patterns(u1=["python"]))

    cur.execute.assert_called_once()
    notify.assert_not_called()


def test_init_schema_creates_keywords_table():
    from db_schema import init_schema
    conn, cur = make_conn()
    init_schema(conn)

    sqls = [" ".join(c.args[0].split()) for c in cur.execute.call_args_list]
    assert any(s.startswith("CREATE TABLE IF NOT EXISTS keywords") for s in sqls)
    assert any("UNIQUE (word, chat_id)" in s for s in sqls)
    conn.commit.assert_called_once()


# ==========================================
# --- Run diagnostics: counters and feed logging ---
# ==========================================
import logging
from collections import Counter

import LeadScanner
from LeadScanner import fetch_feed, format_stats, send_telegram_notification


def run_with_stats(conn, entry, patterns):
    stats = Counter()
    process_entry(conn, entry, "TestSource", {}, patterns, TOKEN, stats)
    return stats


@pytest.mark.parametrize("entry, key", [
    pytest.param({**HOT_ENTRY, "link": ""}, "no_link", id="missing-link"),
    pytest.param({**HOT_ENTRY, "title": "Python developer", "summary": "Flask API"},
                 "no_intent", id="no-intent-word"),
    pytest.param({**HOT_ENTRY, "summary": "Python tutorial, budget $500"},
                 "negative", id="negative-word"),
])
def test_stats_filtered_out(entry, key, ai, notify):
    conn, _ = make_conn()
    stats = run_with_stats(conn, entry, make_patterns(u1=["python"]))
    assert stats == Counter({"entries": 1, key: 1})


def test_stats_no_keyword_match(ai, notify):
    conn, _ = make_conn()
    stats = run_with_stats(conn, HOT_ENTRY, make_patterns(u1=["shopify"]))
    assert stats == Counter({"entries": 1, "no_keyword_match": 1})


def test_stats_ai_failed(ai, notify):
    ai.return_value = None
    conn, _ = make_conn()
    stats = run_with_stats(conn, HOT_ENTRY, make_patterns(u1=["python"]))
    assert stats == Counter({"entries": 1, "matched_users": 1, "ai_failed": 1})


def test_stats_ai_disabled(ai, notify):
    ai.return_value = 0
    conn, _ = make_conn()
    stats = run_with_stats(conn, HOT_ENTRY, make_patterns(u1=["python"]))
    assert stats["ai_disabled"] == 1
    assert stats["inserted"] == 1
    assert stats["below_threshold"] == 1


def test_stats_inserted_and_notified(ai, notify):
    notify.return_value = True
    conn, _ = make_conn()
    stats = run_with_stats(conn, HOT_ENTRY, make_patterns(u1=["python"], u2=["flask"]))
    assert stats == Counter({"entries": 1, "matched_users": 2, "inserted": 2, "notified": 2})


def test_stats_below_threshold(ai, notify):
    ai.return_value = 6
    conn, _ = make_conn()
    stats = run_with_stats(conn, HOT_ENTRY, make_patterns(u1=["python"]))
    assert stats == Counter({"entries": 1, "matched_users": 1, "inserted": 1,
                             "below_threshold": 1})
    notify.assert_not_called()


def test_stats_duplicate(ai, notify):
    conn, _ = make_conn(rowcount=0)
    stats = run_with_stats(conn, HOT_ENTRY, make_patterns(u1=["python"]))
    assert stats == Counter({"entries": 1, "matched_users": 1, "duplicate": 1})


def test_stats_db_error(ai, notify):
    notify.return_value = True
    conn, _ = make_conn(execute_side_effect=[psycopg2.Error("boom"), None])
    stats = run_with_stats(conn, HOT_ENTRY, make_patterns(u1=["python"], u2=["flask"]))
    assert stats["db_error"] == 1
    assert stats["inserted"] == 1
    assert stats["notified"] == 1


def test_stats_notify_failed(ai, notify):
    notify.return_value = False
    conn, _ = make_conn()
    stats = run_with_stats(conn, HOT_ENTRY, make_patterns(u1=["python"]))
    assert stats["notify_failed"] == 1
    assert stats["notified"] == 0


def test_process_entry_without_stats_still_works(ai, notify):
    conn, cur = make_conn()
    process_entry(conn, HOT_ENTRY, "TestSource", {}, make_patterns(u1=["python"]), TOKEN)
    cur.execute.assert_called_once()
    notify.assert_called_once()


def test_format_stats_lists_every_key_with_zero_default():
    line = format_stats(Counter({"entries": 3}))
    assert line.startswith("entries=3 no_link=0")
    assert "notify_failed=0" in line


@patch("LeadScanner.requests.post")
def test_send_telegram_notification_returns_true_on_success(mock_post):
    mock_post.return_value.raise_for_status.return_value = None
    assert send_telegram_notification(TOKEN, "u1", "t", "l", "d", "TestSource") is True


@patch("LeadScanner.requests.post")
def test_send_telegram_notification_returns_false_on_error(mock_post):
    mock_post.side_effect = requests.ConnectionError("down")
    assert send_telegram_notification(TOKEN, "u1", "t", "l", "d", "TestSource") is False


def test_send_telegram_notification_returns_false_without_token():
    assert send_telegram_notification(None, "u1", "t", "l", "d", "TestSource") is False


VALID_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>t</title>
<item><title>Hiring a dev</title><link>https://example.com/1</link></item>
<item><title>Need a site</title><link>https://example.com/2</link></item>
</channel></rss>"""

BLOCKED_HTML = b"<html><body><h1>Blocked</h1><p>Too many requests</p></body></html>"


def fake_response(body, content_type, status=200):
    resp = MagicMock()
    resp.content = body
    resp.status_code = status
    resp.headers = {"Content-Type": content_type}
    resp.raise_for_status.return_value = None
    return resp


@patch("LeadScanner.requests.get")
def test_fetch_feed_valid_rss(mock_get):
    mock_get.return_value = fake_response(VALID_RSS, "application/rss+xml")
    feed, meta = fetch_feed("https://example.com/feed")
    assert len(feed.entries) == 2
    assert meta["status"] == 200
    assert meta["entries"] == 2
    assert meta["bytes"] == len(VALID_RSS)
    assert meta["content_type"] == "application/rss+xml"


@patch("LeadScanner.requests.get")
def test_fetch_feed_html_with_200_gives_zero_entries_without_error(mock_get):
    """A blocked HTML page with status 200 raises nothing. feedparser does not
    even set bozo for well-formed HTML, so entries == 0 plus the content type
    is the signal (log_feed_meta warns on it)."""
    mock_get.return_value = fake_response(BLOCKED_HTML, "text/html; charset=utf-8")
    feed, meta = fetch_feed("https://example.com/feed")
    assert feed.entries == []
    assert meta["entries"] == 0
    assert meta["status"] == 200
    assert meta["content_type"].startswith("text/html")


@patch("LeadScanner.requests.get")
def test_fetch_feed_reports_bozo_reason_for_broken_xml(mock_get):
    mock_get.return_value = fake_response(b"<rss><channel><item>", "application/rss+xml")
    _, meta = fetch_feed("https://example.com/feed")
    assert meta["bozo"] is True
    assert meta["bozo_reason"]


@pytest.fixture
def main_patches():
    """Patch everything main() touches except the sources; yields a setter
    that installs the list build_sources() returns."""
    conn, _ = make_conn()
    with patch("LeadScanner.get_connection", return_value=conn),          patch("LeadScanner.init_schema"),          patch("LeadScanner.load_user_profiles", return_value={"u1": ["python"]}),          patch("LeadScanner.get_ai_score", return_value=8),          patch("LeadScanner.send_telegram_notification", return_value=True),          patch("LeadScanner.build_sources") as build:
        yield lambda sources: setattr(build, "return_value", sources)


@pytest.fixture
def fake_main_env(main_patches):
    """Two RSS sources; the download itself is left to requests.get."""
    main_patches([
        LeadScanner.rss_source("FeedA", "https://example.com/a"),
        LeadScanner.rss_source("FeedB", "https://example.com/b"),
    ])


@patch("LeadScanner.requests.get")
def test_main_warns_on_empty_feed_and_logs_summaries(mock_get, fake_main_env, caplog):
    mock_get.side_effect = [
        fake_response(BLOCKED_HTML, "text/html"),
        fake_response(VALID_RSS, "application/rss+xml"),
    ]
    with caplog.at_level(logging.INFO, logger="leadscanner"):
        LeadScanner.main()

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("FeedA returned 0 entries" in m and "text/html" in m for m in warnings)

    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("FeedA: status=200") and "entries=0" in m for m in messages)
    assert any(m.startswith("FeedA summary: entries=0") for m in messages)
    assert any(m.startswith("FeedB summary: entries=2") for m in messages)
    assert any(m.startswith("Run totals: entries=2") for m in messages)


@patch("LeadScanner.requests.get")
def test_main_does_not_log_feed_urls(mock_get, fake_main_env, caplog):
    mock_get.return_value = fake_response(VALID_RSS, "application/rss+xml")
    with caplog.at_level(logging.INFO, logger="leadscanner"):
        LeadScanner.main()
    assert not any("example.com/a" in r.getMessage() or "example.com/b" in r.getMessage()
                   for r in caplog.records)


# --- Sources ---
def test_build_sources_has_no_reddit_and_every_source_is_callable():
    sources = LeadScanner.build_sources()
    assert sources
    for s in sources:
        assert callable(s["fetch"])
        assert "reddit" not in s["source"].lower()


@patch("LeadScanner.requests.get")
def test_rss_source_returns_entries_and_meta(mock_get):
    mock_get.return_value = fake_response(VALID_RSS, "application/rss+xml")
    entries, meta = LeadScanner.rss_source("X", "https://example.com/x")["fetch"]()
    assert [e["link"] for e in entries] == ["https://example.com/1", "https://example.com/2"]
    assert meta["entries"] == 2
    mock_get.assert_called_once()
    assert mock_get.call_args.args[0] == "https://example.com/x"


def plain_meta(n):
    return {"status": 200, "content_type": "application/json", "bytes": 10,
            "entries": n, "bozo": False, "bozo_reason": ""}


def test_main_runs_a_non_rss_source(main_patches, caplog):
    """A source only has to return (entries, meta); plain dicts work."""
    entries = [{**HOT_ENTRY, "link": "https://example.com/j1"}]
    main_patches([{"source": "JsonSource", "fetch": lambda: (entries, plain_meta(1))}])
    with caplog.at_level(logging.INFO, logger="leadscanner"):
        LeadScanner.main()
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("JsonSource summary: entries=1") and "notified=1" in m
               for m in messages)


def test_main_skips_a_failing_source_and_continues(main_patches, caplog):
    def broken():
        raise requests.ConnectionError("down")
    main_patches([
        {"source": "Broken", "fetch": broken},
        {"source": "Works", "fetch": lambda: ([HOT_ENTRY], plain_meta(1))},
    ])
    with caplog.at_level(logging.INFO, logger="leadscanner"):
        LeadScanner.main()
    messages = [r.getMessage() for r in caplog.records]
    assert any(m == "Failed to fetch Broken" for m in messages)
    assert any(m.startswith("Works summary: entries=1") for m in messages)
