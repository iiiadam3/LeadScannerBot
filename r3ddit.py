import requests
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os

pd.set_option('display.max_colwidth', None)


# --- פונקציה 1: שאיבת הנתונים מרדיט וסינון ---
def get_reddit_leads_bypass(subreddit_name, intent_keywords, context_keywords, negative_keywords, limit=100):
    url = f"https://www.reddit.com/r/{subreddit_name}/new.json?limit={limit}"

    # התיקון הקריטי: User-Agent חוקי לפי הכללים של רדיט כדי למנוע חסימה
    headers = {'User-Agent': 'windows:AdamRedditLeadBot:v1.0 (by /u/Fearless_Ant674)'}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        leads = []
        for post in data['data']['children']:
            post_data = post['data']
            title = post_data.get('title', '').lower()
            text = post_data.get('selftext', '').lower()
            content = title + " " + text

            # סינון חכם 2D
            contains_intent = any(keyword in content for keyword in intent_keywords)
            contains_context = any(keyword in content for keyword in context_keywords)
            contains_negative = any(neg_keyword in content for neg_keyword in negative_keywords)

            if contains_intent and contains_context and not contains_negative:
                leads.append({
                    "Date": datetime.fromtimestamp(post_data.get('created_utc', 0)).strftime('%Y-%m-%d %H:%M'),
                    "Title": post_data.get('title', ''),
                    "Link": f"https://www.reddit.com{post_data.get('permalink', '')}",
                    "Score": post_data.get('score', 0)
                })

        return pd.DataFrame(leads)

    except Exception as e:
        print(f"Error fetching data: {e}")
        return pd.DataFrame()


# --- פונקציה 2: שליחת האימייל ---
def send_leads_email(csv_file_path, sender_email, app_password, receiver_email):
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = "הלידים היומיים שלך מרדיט מוכנים! 🚀"

    body = "היי! הסקריפט סיים לרוץ. מצורף קובץ הלידים המעודכן להיום."
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        with open(csv_file_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())

        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(csv_file_path)}")
        msg.attach(part)
    except Exception as e:
        print(f"Error attaching file: {e}")
        return

    try:
        print("Connecting to Gmail server...")
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, app_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        server.quit()
        print(f"✅ Success! Email sent to {receiver_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


# ==========================================
# --- הפעלת התוכנית המרכזית (Main) ---
# ==========================================
def main():
    target_subreddit = "shopify+wordpress+smallbusiness+forhire"

    # עברנו לביטויים שמראים כוונה אמיתית לשכור או לבקש עזרה מקצועית (Intent)
    intent_phrases = [
        "looking for a developer", "hire a", "hiring", "need a website",
        "need help with my website", "need someone to", "budget is",
        "paid task", "paid gig", "willing to pay", "can't code"
    ]

    # מילים שחייבות להופיע כדי להוכיח שמדובר בטכנולוגיה (Context)
    context_keywords = [
        "shopify", "wordpress", "website", "developer", "plugin",
        "ecommerce", "e-commerce", "coding", "html", "css"
    ]

    # הרחבנו את מילות השלילה שמסננות רעש (Negative)
    negative_keywords = [
        "hire me", "my portfolio", "starting a", "video editor",
        "for hire", "how to learn", "student", "auto", "insurance",
        "loan", "tax", "news", "article", "ransomware", "second hand"
    ]

    print("Scraping Reddit with Upgraded NLP-Style Filtering...")
    # כאן אנחנו מעבירים את ה-intent_phrases במקום מילים בודדות
    leads_df = get_reddit_leads_bypass(target_subreddit, intent_phrases, context_keywords, negative_keywords, limit=100)

    if not leads_df.empty:
        print(f"Found {len(leads_df)} highly relevant leads!")

        filename = "filtered_reddit_leads.csv"
        leads_df.to_csv(filename, index=False, encoding='utf-8')
        print("Saved leads to file.")

        # --- פרטי המייל ---
        SENDER_EMAIL = "iadam314@gmail.com"

        # כאן השינוי החשוב! מוחקים את הסיסמה הגלויה ומשתמשים במשתנה סביבה
        APP_PASSWORD = os.environ.get("elvtghanwpbeiael")

        RECEIVER_EMAIL = "iadam314@gmail.com"


        send_leads_email(filename, SENDER_EMAIL, APP_PASSWORD, RECEIVER_EMAIL)
    else:
        print("No relevant leads found after filtering.")


if __name__ == "__main__":
    main()