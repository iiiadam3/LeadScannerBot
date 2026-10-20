import logging
import os
import re
from contextlib import closing

import feedparser
import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("leadscanner")

DATABASE_URL = os.environ.get("DATABASE_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Timeouts in seconds: (connect, read). Without them requests can hang forever.
HTTP_TIMEOUT = (5, 20)

# An honest, identifiable User-Agent instead of a spoofed browser one.
USER_AGENT = "LeadScannerBot/1.0 (personal lead-aggregation project)"

# ==========================================
# --- Global filter lists ---
# ==========================================
GLOBAL_INTENT = ["hiring", "looking for", "budget", "paid", "need a", "hire", "wanted", "seeking"]
GLOBAL_NEGATIVE = ["for free", "how to", "tutorial", "student", "course", "unpaid",
                   "advice on", "help me learn", "for hire", "[for hire]"]


# ==========================================
# --- Keyword matching ---
# ==========================================
def compile_keyword_pattern(keywords):
    """Build one regex that matches any keyword as a whole word / phrase.

    (?<!\\w) and (?!\\w) act like \\b but also work for keywords that start or
    end with a non-word character, such as "c++" or "[for hire]".
    Returns None for an empty list.
    """
    cleaned = [k.strip() for k in keywords if k and k.strip()]
    if not cleaned:
        return None
    parts = [re.escape(k) for k in cleaned]
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


INTENT_RE = compile_keyword_pattern(GLOBAL_INTENT)
NEGATIVE_RE = compile_keyword_pattern(GLOBAL_NEGATIVE)


# ==========================================
# --- Database ---
# ==========================================
def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(DATABASE_URL)


def init_schema(conn):
    """Idempotent schema setup. Runs inside the caller's connection."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id SERIAL PRIMARY KEY,
                date TEXT,
                title TEXT,
                link TEXT,
                score INTEGER,
                ai_score INTEGER,
                chat_id TEXT,
                CONSTRAINT leads_link_chat_id_key UNIQUE (link, chat_id)
            );
            """
        )
        # One-time cleanup of the legacy single-column constraint (no CASCADE needed).
        cur.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_link_key;")
    conn.commit()


def load_user_profiles(conn):
    """Return {chat_id: [context keywords]}."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT word, chat_id FROM keywords "
            "WHERE category = 'context' AND chat_id IS NOT NULL;"
        )
        rows = cur.fetchall()

    profiles = {}
    for word, chat_id in rows:
        profiles.setdefault(chat_id, []).append(word)
    return profiles


# ==========================================
# --- External services: OpenAI and Telegram ---
# ==========================================
def get_ai_score(title, description):
    """Return an int 1-10, 0 if AI scoring is disabled, or None on failure.

    None (not a fake score) lets the caller skip the lead so it is retried on
    the next run instead of being stored with a misleading value.
    """
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY is not set; AI scoring disabled")
        return 0

    prompt = (
        "You are a lead scoring bot for a freelancer. Rate the intent of this post "
        "to hire or pay for a digital service from 1 to 10. Return ONLY the number. "
        f"Title: {title}. Content: {description}"
    )
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()
        score = int(raw)
        if not 1 <= score <= 10:
            raise ValueError(f"score out of range: {score}")
        return score
    except (requests.RequestException, KeyError, IndexError, ValueError):
        logger.exception("OpenAI scoring failed for %r", title)
        return None


def send_telegram_notification(bot_token, chat_id, title, link, date_str, source):
    if not bot_token or not chat_id:
        return

    message = (
        f"🎯 *ליד חדש מ-{source}!*\n\n"
        f"📌 *כותרת:* {title}\n"
        f"📅 *תאריך:* {date_str}\n\n"
        f"🔗 [לחץ כאן לפתיחת הפוסט]({link})"
    )
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException:
        # Do not log the URL: it contains the bot token.
        logger.error("Telegram notification to chat %s failed", chat_id, exc_info=False)


# ==========================================
# --- Feeds ---
# ==========================================
def build_feeds():
    subreddits = ("shopify+wordpress+smallbusiness+forhire+startups+Entrepreneur"
                  "+freelance+webdev+programmingrequests")
    return [
        {"source": "Reddit", "url": f"https://www.reddit.com/r/{subreddits}/new.rss"},
        {"source": "WeWorkRemotely",
         "url": "https://weworkremotely.com/categories/remote-programming-jobs.rss"},
    ]


def fetch_feed(url):
    """Download with an explicit timeout, then hand the bytes to feedparser."""
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return feedparser.parse(response.content)


# ==========================================
# --- Main ---
# ==========================================
def process_entry(conn, entry, source, profiles, patterns, telegram_token):
    title = entry.get("title", "")
    summary = entry.get("summary", "")
    link = entry.get("link", "")
    date_str = entry.get("published", "No Date")
    content = f"{title} {summary}"

    if not link:
        return

    if not INTENT_RE.search(content) or NEGATIVE_RE.search(content):
        return

    ai_score = None
    for chat_id, pattern in patterns.items():
        if not pattern.search(content):
            continue

        if ai_score is None:
            ai_score = get_ai_score(title, summary)
            if ai_score is None:
                return  # AI failed: skip, retry on the next run

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO leads (date, title, link, score, ai_score, chat_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (link, chat_id) DO NOTHING
                    """,
                    (date_str, title, link, 0, ai_score, chat_id),
                )
                is_new = cur.rowcount > 0
            conn.commit()
        except psycopg2.Error:
            logger.exception("DB error saving lead for user %s", chat_id)
            conn.rollback()
            continue

        if is_new and ai_score >= 7:
            send_telegram_notification(
                telegram_token, chat_id, f"🔥 ציון: {ai_score} | {title}",
                link, date_str, source,
            )


def main():
    telegram_token = os.environ.get("TELEGRAM_TOKEN")

    # closing() guarantees conn.close() even if an exception escapes.
    with closing(get_connection()) as conn:
        init_schema(conn)
        profiles = load_user_profiles(conn)

        if not profiles:
            logger.info("No active users with contexts found.")
            return

        # Compile each user's regex once, not once per post.
        patterns = {cid: compile_keyword_pattern(words) for cid, words in profiles.items()}
        patterns = {cid: p for cid, p in patterns.items() if p is not None}
        logger.info("Found %d active users. Starting aggregation...", len(patterns))

        for feed_info in build_feeds():
            source = feed_info["source"]
            logger.info("Fetching from %s...", source)
            try:
                feed = fetch_feed(feed_info["url"])
            except requests.RequestException:
                logger.exception("Failed to fetch %s", source)
                continue

            for entry in feed.entries:
                process_entry(conn, entry, source, profiles, patterns, telegram_token)

    logger.info("Multi-source scrape completed.")


if __name__ == "__main__":
    main()
