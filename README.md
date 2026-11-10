# LeadScannerBot 🎯

Finds people who are looking to pay for freelance work, scores how serious they are with an LLM, and sends the good ones to Telegram. Each user sets their own keywords, so one bot serves several freelancers.

## How it works

1. **Every 6 hours**, a GitHub Actions job runs the scanner.
2. It pulls two RSS feeds: a set of subreddits (`r/forhire`, `r/webdev`, `r/startups` and others) and WeWorkRemotely's remote programming jobs.
3. **First filter, regex.** A post has to contain a hiring word ("hiring", "budget", "looking for") and must not contain a disqualifying one ("tutorial", "unpaid", "for hire"). Matching is whole-word, so "ai" does not match inside "email", and it still works for keywords like `c++`.
4. **Second filter, per user.** Each user's own keywords are compiled into one regex and matched against the post.
5. **Scoring.** A post that survives both filters goes to the OpenAI API (`gpt-4o-mini`), which rates buying intent from 1 to 10. If the call fails the post is skipped entirely rather than stored with a made-up score, so the next run retries it.
6. **Storing and alerting.** Leads go into PostgreSQL with a `UNIQUE (link, chat_id)` constraint and `ON CONFLICT DO NOTHING`, so the same post is never sent twice. Only scores of 7 or above trigger a Telegram message.

The Telegram bot is a separate Flask service. Users add and remove keywords and check their stats through it.

## Design notes

- **The bot is push, not pull.** Telegram posts updates to a webhook URL, so the app registers that URL with Telegram on startup, using Render's `RENDER_EXTERNAL_URL` (or `WEBHOOK_URL` if set). Doing it in code rather than by hand means a redeploy cannot silently leave the bot unreachable.
- **Buttons carry a digest, not the keyword.** Telegram caps `callback_data` at 64 bytes, and Hebrew costs 2 bytes per letter, so a long keyword would overflow it. Delete buttons carry a 16-character hash instead, and the keyword is looked up from it.
- **User text is escaped before it goes into a message.** Telegram's Markdown treats `_`, `*`, `` ` `` and `[` as formatting, so a keyword like `node_js` used to make the whole message fail to send with a 400.
- **Failures are contained.** Requests have timeouts, database errors roll back and skip that lead rather than killing the run, and the bot token is never written to a log.

## Known limitation: the free tier sleeps

The bot runs on Render's free plan, which suspends a service after about 15 minutes without traffic. Waking it takes roughly a minute, and Telegram gives up before that and retries, so the first message after a quiet period can take a minute to get an answer. Telegram queues undelivered updates and redelivers them, so nothing is lost. A paid instance removes the delay.

## Testing

`pytest` covers the parts worth protecting: whole-word keyword matching, the AI scoring path including failures and out-of-range answers, Markdown escaping, the 64-byte button limit, and webhook registration (including no URL configured and Telegram being unreachable). Nothing in the suite touches the network or a database. GitHub Actions runs it on every push and pull request.

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

## Run it yourself

```bash
git clone https://github.com/iiiadam3/LeadScannerBot.git
cd LeadScannerBot
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file (git-ignored):

```env
TELEGRAM_TOKEN=<token from @BotFather>
DATABASE_URL=<postgresql connection url>
OPENAI_API_KEY=<openai key>
WEBHOOK_URL=<public https url of the bot service>   # optional; Render sets its own
```

```bash
python LeadScanner.py     # one scan
python bot_manager.py     # the Telegram bot
```

In production the bot runs under gunicorn: `gunicorn bot_manager:app`.

## Tech stack

Python · Flask · pyTelegramBotAPI · PostgreSQL (Supabase) · OpenAI API · GitHub Actions · pytest

## Screenshots

<img width="547" height="393" alt="Telegram bot menu" src="https://github.com/user-attachments/assets/8d68c2f7-77a9-4535-aeda-cb468e5a7ed7" />
<img width="598" height="782" alt="Lead notification" src="https://github.com/user-attachments/assets/d0f0865d-1a8e-4623-8e80-28c1f381b7a3" />
