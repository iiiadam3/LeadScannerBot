import urllib.parse
import os
import requests
import feedparser
# הוסף את השורה הזו כדי לעקוף את החסימה של Upwork:
feedparser.USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
import psycopg2
import pandas as pd
from dotenv import load_dotenv


load_dotenv() # פוקד על פייתון לקרוא את קובץ ה-.env המקומי

pd.set_option('display.max_colwidth', None)

DATABASE_URL = os.environ.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# ==========================================
# --- עדכון סכמה אוטומטי ---
# ==========================================
try:
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS leads (
        id SERIAL PRIMARY KEY,
        date TEXT,
        title TEXT,
        link TEXT,
        score INTEGER,
        ai_score INTEGER,
        chat_id TEXT
    );
    ''')
    cursor.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_link_key CASCADE;")
    cursor.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_link_chat_id_key CASCADE;")
    cursor.execute("ALTER TABLE leads ADD CONSTRAINT leads_link_chat_id_key UNIQUE (link, chat_id);")
    conn.commit()
except Exception as e:
    print(f"Schema update notice: {e}")
    conn.rollback()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# ==========================================
# --- רשימות סינון גלובליות (מנוע ה-Backend) ---
# ==========================================
GLOBAL_INTENT = ["hiring", "looking for", "budget", "paid", "need a", "hire", "wanted", "seeking"]
GLOBAL_NEGATIVE = ["for free", "how to", "tutorial", "student", "course", "unpaid", "advice on", "help me learn"]


# ==========================================
# --- פונקציות עזר: AI וטלגרם ---
# ==========================================
def get_ai_score(title, description):
    if not OPENAI_API_KEY:
        return 0

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }

    prompt = f"You are a lead scoring bot for a freelancer. Rate the intent of this post to hire or pay for a digital service from 1 to 10. Return ONLY the number. Title: {title}. Content: {description}"

    data = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        score = int(response.json()['choices'][0]['message']['content'].strip())
        return score
    except Exception as e:
        print("AI Error:", e)
        return 1


def send_telegram_notification(bot_token, chat_id, title, link, date_str, source):
    if not bot_token or not chat_id:
        return

    message = (
        f"🎯 *ליד חדש מ-{source}!*\n\n"
        f"📌 *כותרת:* {title}\n"
        f"📅 *תאריך:* {date_str}\n\n"
        f"🔗 [לחץ כאן לפתיחת הפוסט]({link})"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram error: {e}")


# ==========================================
# --- הפעלת התוכנית המרכזית (Main) ---
# ==========================================
def main():
    telegram_token = os.environ.get("TELEGRAM_TOKEN")

    # משיכת תחומי ההתמחות בלבד מהמשתמשים (קטגוריית context)
    cursor.execute("SELECT word, chat_id FROM keywords WHERE category = 'context' AND chat_id IS NOT NULL;")
    rows = cursor.fetchall()

    user_profiles = {}
    for word, chat_id in rows:
        if chat_id not in user_profiles:
            user_profiles[chat_id] = []
        user_profiles[chat_id].append(word)

    if not user_profiles:
        print("No active users with contexts found.")
        return

    print(f"Found {len(user_profiles)} active users. Starting aggregation...")

    target_subreddit = "shopify+wordpress+smallbusiness+forhire+startups+Entrepreneur+freelance+webdev+programmingrequests"

    rss_feeds = [
        {"source": "Reddit", "url": f"https://www.reddit.com/r/{target_subreddit}/new.rss"}
    ]

    # 2. הוספה דינמית של פידים מ-Upwork על בסיס מילות המפתח שהמשתמשים הזינו בטלגרם
    # (בהנחה ש-context_keywords נשלף לפני כן ממסד הנתונים)
    # איסוף כל מילות המפתח של כל המשתמשים לרשימה אחת ללא כפילויות
    all_keywords = set()
    for keywords in user_profiles.values():
        all_keywords.update(keywords)

    # הוספה דינמית של פידים מ-Upwork על בסיס המילים שנאספו
    for word in all_keywords:
        safe_word = urllib.parse.quote(word)
        rss_feeds.append({
            "source": "Upwork",
            "url": f"https://www.upwork.com/ab/feed/jobs/rss?sort=recency&q={safe_word}"
        })

    agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36'

    for feed_info in rss_feeds:
        source_name = feed_info["source"]
        feed_url = feed_info["url"]
        print(f"Fetching from {source_name}...")

        try:
            feed = feedparser.parse(feed_url, agent=agent)
        except Exception as e:
            print(f"Failed to fetch {source_name}: {e}")
            continue



        for entry in feed.entries:
            title = entry.get('title', '').lower()
            text = entry.get('summary', '').lower()
            content = title + " " + text

            lead_title = entry.get('title', '')
            print(f"Scanning post: {lead_title}")
            lead_link = entry.get('link', '')
            lead_date = entry.get('published', 'No Date')

            ai_score = None

            for chat_id, context_keywords in user_profiles.items():
                if not context_keywords:
                    continue

                # שימוש ברשימות הגלובליות מול ההקשר הספציפי של המשתמש
                contains_intent = any(k in content for k in GLOBAL_INTENT)
                contains_context = any(k in content for k in context_keywords)
                contains_negative = any(k in content for k in GLOBAL_NEGATIVE)

                if contains_intent and contains_context and not contains_negative:
                    if ai_score is None:
                        ai_score = get_ai_score(entry.get('title', ''), entry.get('summary', ''))

                    try:
                        cursor.execute('''
                        INSERT INTO leads (date, title, link, score, ai_score, chat_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (link, chat_id) DO NOTHING
                        ''', (lead_date, lead_title, lead_link, 0, ai_score, chat_id))

                        if cursor.rowcount > 0 and ai_score >= 7:
                            title_with_score = f"🔥 ציון: {ai_score} | {lead_title}"
                            send_telegram_notification(telegram_token, chat_id, title_with_score, lead_link, lead_date,
                                                       source_name)

                    except Exception as e:
                        print(f"DB Error for user {chat_id}: {e}")
                        conn.rollback()

    conn.commit()
    conn.close()
    print("Multi-source scrape completed successfully.")


if __name__ == "__main__":
    main()