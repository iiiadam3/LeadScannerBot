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