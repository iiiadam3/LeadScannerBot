import logging
import os
import re
from collections import Counter
from contextlib import closing

import feedparser
import psycopg2
import requests
from dotenv import load_dotenv

from db_schema import init_schema

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
    """Return True if Telegram accepted the message, False otherwise."""
    if not bot_token or not chat_id:
        return False

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
        return True
    except requests.RequestException:
        # Do not log the URL: it contains the bot token.
        logger.error("Telegram notification to chat %s failed", chat_id, exc_info=False)
        return False


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
    """Download with an explicit timeout, then hand the bytes to feedparser.

    Returns (feed, meta). meta describes the HTTP response so the caller can
    log it: feedparser never raises on a non-feed body (e.g. an HTML "blocked"
    page served with 200), it just returns zero entries and sets bozo.
    """
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    meta = {
        "status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "bytes": len(response.content),
        "entries": len(feed.entries),
        "bozo": bool(feed.get("bozo")),
        "bozo_reason": str(feed.get("bozo_exception", "")) if feed.get("bozo") else "",
    }
    return feed, meta


def log_feed_meta(source, meta):
    """Log one line per download; warn when a feed came back empty."""
    logger.info(
        "%s: status=%s content_type=%r bytes=%d entries=%d bozo=%s%s",
        source, meta["status"], meta["content_type"], meta["bytes"], meta["entries"],
        meta["bozo"], f" ({meta['bozo_reason']})" if meta["bozo_reason"] else "",
    )
    if meta["entries"] == 0:
        logger.warning(
            "%s returned 0 entries (status=%s, content_type=%r) - possibly blocked "
            "or not a feed", source, meta["status"], meta["content_type"],
        )


STAT_KEYS = (
    "entries", "no_link", "no_intent", "negative", "no_keyword_match",
    "matched_users", "ai_failed", "ai_disabled", "inserted", "duplicate",
    "db_error", "below_threshold", "notified", "notify_failed",
)


def format_stats(stats):
    return " ".join(f"{k}={stats.get(k, 0)}" for k in STAT_KEYS)


# ==========================================
# --- Main ---
# ==========================================
def process_entry(conn, entry, source, profiles, patterns, telegram_token, stats=None):
    """stats: optional collections.Counter; only counted into, never read."""
    if stats is None:
        stats = Counter()  # throwaway, so the code below needs no None checks

    title = entry.get("title", "")
    summary = entry.get("summary", "")
    link = entry.get("link", "")
    date_str = entry.get("published", "No Date")
    content = f"{title} {summary}"
    stats["entries"] += 1

    if not link:
        stats["no_link"] += 1
        return

    if not INTENT_RE.search(content):
        stats["no_intent"] += 1
        return
    if NEGATIVE_RE.search(content):
        stats["negative"] += 1
        return

    ai_score = None
    matched_any = False
    for chat_id, pattern in patterns.items():
        if not pattern.search(content):
            continue
        matched_any = True
        stats["matched_users"] += 1

        if ai_score is None:
            ai_score = get_ai_score(title, summary)
            if ai_score is None:
                stats["ai_failed"] += 1
                return  # AI failed: skip, retry on the next run
            if ai_score == 0:
                stats["ai_disabled"] += 1

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
            stats["db_error"] += 1
            continue

        if not is_new:
            stats["duplicate"] += 1
            continue
        stats["inserted"] += 1

        if ai_score >= 7:
            sent = send_telegram_notification(
                telegram_token, chat_id, f"🔥 ציון: {ai_score} | {title}",
                link, date_str, source,
            )
            stats["notified" if sent else "notify_failed"] += 1
        else:
            stats["below_threshold"] += 1

    if not matched_any:
        stats["no_keyword_match"] += 1


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

        totals = Counter()
        for feed_info in build_feeds():
            source = feed_info["source"]
            logger.info("Fetching from %s...", source)
            try:
                feed, meta = fetch_feed(feed_info["url"])
            except requests.RequestException:
                logger.exception("Failed to fetch %s", source)
                continue
            log_feed_meta(source, meta)

            stats = Counter()
            for entry in feed.entries:
                process_entry(conn, entry, source, profiles, patterns, telegram_token, stats)
            logger.info("%s summary: %s", source, format_stats(stats))
            totals.update(stats)

        logger.info("Run totals: %s", format_stats(totals))

    logger.info("Multi-source scrape completed.")


if __name__ == "__main__":
    main()
