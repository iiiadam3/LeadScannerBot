# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt -r requirements-dev.txt   # pytest lives in requirements-dev.txt
pytest                                    # all tests (test_scanner.py, test_bot_manager.py)
pytest test_scanner.py::test_notification_threshold   # single test
pytest -k "ai_score"                      # tests matching a name
python LeadScanner.py                     # one scan cycle (needs DATABASE_URL; OPENAI_API_KEY/TELEGRAM_TOKEN optional)
python bot_manager.py                     # Flask server for the Telegram bot (PORT, default 10000); also the Render start command
gunicorn bot_manager:app                  # alternative production server (not used on Render today)
```

Env vars are loaded from a git-ignored `.env`: `TELEGRAM_TOKEN`, `DATABASE_URL`, `OPENAI_API_KEY`, and optionally `WEBHOOK_URL` (on Render, `RENDER_EXTERNAL_URL` is set automatically).

No linter or formatter is configured.

## CI

- `.github/workflows/tests.yml` runs `pytest -q` on every push and pull request (Python 3.12, installs `requirements.txt` and `requirements-dev.txt`).
- `.github/workflows/scraper.yml` runs `python LeadScanner.py` on cron `0 */6 * * *` plus manual dispatch, with `DATABASE_URL`, `TELEGRAM_TOKEN` and `OPENAI_API_KEY` from repo secrets.

## Architecture

Two independent processes share one PostgreSQL database (Supabase). Neither imports the other; both import `db_schema.py`.

- **`db_schema.py`**: `init_schema(conn)` creates `leads` (with `UNIQUE (link, chat_id)`) and `keywords` (with `UNIQUE (word, chat_id)`) if they are missing, drops the legacy `leads_link_key` constraint, and commits. Both processes call it on the same database, so every statement must stay idempotent (`IF NOT EXISTS` / `IF EXISTS`).
- **`LeadScanner.py`**: a batch job run by the scraper workflow. One run of `main()` does this:
  1. Calls `init_schema`.
  2. Loads each user's keywords (`keywords` rows with `category = 'context'`) and compiles one regex per `chat_id`.
  3. Calls `fetch()` on each source in `build_sources()` (today only WeWorkRemotely's RSS feed) and runs `process_entry` on each entry. A failing source is logged and skipped.
  - A source is `{"source": name, "fetch": callable}`. `fetch()` returns `(entries, meta)`: the entries are dict-like with `title`/`summary`/`link`/`published`, and `meta` has the keys `log_feed_meta` prints. `rss_source(name, url)` builds one for an RSS/Atom feed. A JSON API source needs its own fetch function that maps its fields to those keys.
  - Reddit was removed in Nov 2026, after its RSS was shut down (the feed returns 404) and its API started requiring approval.
- **`bot_manager.py`**: a Flask + pyTelegramBotAPI webhook server deployed on Render with the start command `python bot_manager.py`. Telegram POSTs to `/<TELEGRAM_TOKEN>`. Users add and delete keywords and view stats through inline-keyboard callbacks (`add_service`, `manage_services`, `del_srv_<digest>`, `menu_stats`, `main_menu`). It writes to `keywords` and reads `leads`.
  - Importing the module has side effects, on purpose, so startup also works under a server such as gunicorn, which never runs `__main__`: it raises `RuntimeError` if `TELEGRAM_TOKEN` is unset (the route is built from the token), then calls `ensure_schema()` (runs `init_schema` with a 10 s connect timeout) and `configure_webhook()` (registers `WEBHOOK_URL` or `RENDER_EXTERNAL_URL` with Telegram). Both log and return `False` on failure or missing config instead of stopping startup.
  - Delete buttons carry `del_srv_` + a 16-char SHA-256 digest of the keyword (`service_token`), because Telegram caps `callback_data` at 64 bytes and Hebrew costs 2 bytes per letter. `delete_service` looks the keyword up by digest among the user's keywords.
  - User-supplied text goes through `escape_markdown` before being put into a Markdown message. Keywords are lowercased, stripped and capped at `MAX_KEYWORD_LENGTH = 60`.

### Filtering pipeline (`process_entry`)
Each check is cheaper than the next one, and the order matters:
1. Skip the entry if it has no link.
2. Run the global `INTENT_RE` and `NEGATIVE_RE` over title + summary. The entry needs an intent word and no negative word.
3. Match each user's keyword regex.
4. Call OpenAI (`gpt-4o-mini`, score 1–10) **at most once per entry**, lazily, and only if some user matched. The score is shared by every matching user.
5. Insert with `ON CONFLICT (link, chat_id) DO NOTHING`. `cur.rowcount > 0` means the lead is new.
6. Send a Telegram notification only if the lead is new **and** `ai_score >= 7`.

Return-value contract of `get_ai_score`:
- `None` means the call failed (network error, bad response, or a score outside 1–10). The entry is skipped without being saved, so the next run retries it.
- `0` means AI is disabled because `OPENAI_API_KEY` is unset. The lead is saved but never notified.

A DB error for one user rolls back and moves on to the next user.

### Keyword matching
`compile_keyword_pattern` escapes keywords and wraps them in `(?<!\w)…(?!\w)` instead of `\b`. That way keywords such as `c++` or `[for hire]` still match as whole words. It returns `None` for an empty list, and callers filter that out.

### Database notes
- Table definitions live only in `db_schema.py`. A schema change goes there and must stay idempotent, because both processes run it.
- `chat_id` is stored as TEXT. Both processes convert it with `str(...)`.

## Conventions
- User-facing Telegram text (bot menus, notifications) is in **Hebrew** and uses Telegram `Markdown` parse mode. Some comments in `bot_manager.py` are also Hebrew.
- Every outbound HTTP call in `LeadScanner.py` uses `HTTP_TIMEOUT = (5, 20)`. Never log Telegram API URLs or the webhook URL with the token, because they contain the bot token.
- Tests mock everything external; no real DB or network is needed.
  - `test_scanner.py` patches `LeadScanner.requests.post`, `LeadScanner.OPENAI_API_KEY`, `LeadScanner.get_ai_score` and `LeadScanner.send_telegram_notification`, and uses a `MagicMock` connection whose `cursor()` works as a context manager (`make_conn`).
  - `test_bot_manager.py` sets a fake `TELEGRAM_TOKEN` and an empty `DATABASE_URL` in `os.environ` **before** importing `bot_manager`, so the import-time schema setup is skipped. Tests use `monkeypatch` on `bot_manager.bot`, `bot_manager.psycopg2.connect` and `bot_manager.init_schema`. The missing-token test also patches `dotenv.load_dotenv` so a local `.env` cannot restore the token.

## Working with me
- Explain the plan briefly before making changes, and wait for approval.
- Work in small steps. Ask before large or multi-file changes.
- Never commit or push without asking.
- On this machine, run tests with: `.venv1\Scripts\python.exe -m pytest -v`
