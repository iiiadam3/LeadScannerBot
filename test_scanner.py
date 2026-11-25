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
    "link": "https://reddit.com/r/forhire/abc",
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
    process_entry(conn, entry, "Reddit", {}, patterns, TOKEN)


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
        assert (token, chat_id, link, source) == (TOKEN, "u1", HOT_ENTRY["link"], "Reddit")
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
    from LeadScanner import init_schema
    conn, cur = make_conn()
    init_schema(conn)

    sqls = [" ".join(c.args[0].split()) for c in cur.execute.call_args_list]
    assert any(s.startswith("CREATE TABLE IF NOT EXISTS keywords") for s in sqls)
    assert any("UNIQUE (word, chat_id)" in s for s in sqls)
    conn.commit.assert_called_once()
