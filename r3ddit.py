import os
import requests
import pandas as pd
from datetime import datetime
import psycopg2
import feedparser

pd.set_option('display.max_colwidth', None)

# ==========================================
# --- הגדרת מסד הנתונים (PostgreSQL Cloud) ---
# ==========================================
DATABASE_URL = os.environ.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# יצירת טבלת לידים
cursor.execute('''
CREATE TABLE IF NOT EXISTS leads (
    id SERIAL PRIMARY KEY,
    date TEXT,
    title TEXT,
    link TEXT UNIQUE,
    score INTEGER
)
''')
conn.commit()


# ==========================================
# --- פונקציה: שליחת התראה ל-Telegram ---
# ==========================================
def send_telegram_notification(bot_token, chat_id, title, link, date_str):
    if not bot_token or not chat_id:
        print("Telegram token or chat ID is missing. Skipping Telegram notification.")
        return

    message = (
        f"🎯 *ליד חדש נמצא ברדיט!*\n\n"
        f"📌 *כותרת:* {title}\n"
        f"📅 *תאריך:* {date_str}\n\n"
        f"🔗 [לחץ כאן לפתיחת הפוסט ברדיט]({link})"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("Successfully sent alert to Telegram!")
        else:
            print(f"Failed to send Telegram alert. Status code: {response.status_code}, Error: {response.text}")
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")


# ==========================================
# --- פונקציה 1: שאיבת הנתונים מרדיט (RSS) ---
# ==========================================
def get_reddit_leads_bypass(subreddit_name, intent_keywords, context_keywords, negative_keywords):
    url = f"https://www.reddit.com/r/{subreddit_name}/new.rss"
    agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36'

    telegram_token = os.environ.get("TELEGRAM_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    try:
        feed = feedparser.parse(url, agent=agent)
        leads = []
        for entry in feed.entries:
            title = entry.get('title', '').lower()
            text = entry.get('summary', '').lower()
            content = title + " " + text

            # סינון חכם
            contains_intent = any(keyword in content for keyword in intent_keywords)
            contains_context = any(keyword in content for keyword in context_keywords)
            contains_negative = any(neg_keyword in content for neg_keyword in negative_keywords)

            if contains_intent and contains_context and not contains_negative:
                lead_date = entry.get('published', 'No Date')
                lead_title = entry.get('title', '')
                lead_link = entry.get('link', '')
                lead_score = 0

                # ניסיון הכנסה למסד הנתונים בענן
                cursor.execute('''
                INSERT INTO leads (date, title, link, score)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (link) DO NOTHING
                ''', (lead_date, lead_title, lead_link, lead_score))

                # אם הליד חדש לחלוטין (ולא נשמר בעבר)
                if cursor.rowcount > 0:
                    leads.append({
                        "Date": lead_date,
                        "Title": lead_title,
                        "Link": lead_link,
                        "Score": lead_score
                    })
                    # שליחת התראה מידית לטלגרם!
                    send_telegram_notification(telegram_token, telegram_chat_id, lead_title, lead_link, lead_date)

        conn.commit()
        return pd.DataFrame(leads)
    except Exception as e:
        print(f"Error fetching data: {e}")
        return pd.DataFrame()


# ==========================================
# --- הפעלת התוכנית המרכזית (Main) ---
# ==========================================
def main():
    # הרחבנו את הסאברדיטים לקהילות יזמים, פרילנסרים ובקשות פיתוח
    target_subreddit = "shopify+wordpress+smallbusiness+forhire+startups+Entrepreneur+freelance+webdev+programmingrequests"

    intent_phrases = [
        "looking for a developer", "hire a", "hiring", "need a website",
        "need help with my website", "need someone to", "budget is",
        "paid task", "paid gig", "willing to pay", "can't code",
        "looking for a programmer", "need a dev", "build an app",
        "build a website", "seeking a developer"
    ]

    context_keywords = [
        "shopify", "wordpress", "website", "developer", "plugin",
        "ecommerce", "e-commerce", "coding", "html", "css",
        "react", "python", "app", "software", "api", "integration",
        "frontend", "backend", "fullstack"
    ]

    negative_keywords = [
        "hire me", "my portfolio", "starting a", "video editor",
        "for hire", "how to learn", "student", "auto", "insurance",
        "loan", "tax", "news", "article", "ransomware", "second hand",
        "seeking work", "looking for work", "feedback", "review my"
    ]

    print("Scraping Reddit via RSS & Monitoring for Telegram alerts...")
    leads_df = get_reddit_leads_bypass(target_subreddit, intent_phrases, context_keywords, negative_keywords)

    if not leads_df.empty:
        print(f"Found {len(leads_df)} NEW highly relevant leads!")
    else:
        print("No new relevant leads found at this time.")

    if conn:
        conn.close()


if __name__ == "__main__":
    main()
