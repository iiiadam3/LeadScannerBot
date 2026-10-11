import os
import telebot
from telebot import types
import psycopg2
from flask import Flask
import threading

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)


# ראוט פשוט כדי ש-Render ידע שהשרת חי
@app.route('/')
def alive():
    return "Bot is alive!"


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


# ==========================================
# --- תפריט ראשי והודעת פתיחה ---
# ==========================================
@bot.message_handler(commands=['start', 'menu', 'help'])
def send_menu(message):
    welcome_text = (
        "👋 *ברוך הבא למערכת איתור הלקוחות החכמה!*\n\n"
        "אנחנו סורקים את הרשת 24/7 כדי למצוא יזמים ולקוחות שמחפשים לשלם על שירותים דיגיטליים, "
        "ומעבירים אותם סינון AI כדי לוודא שמדובר בליד רותח.\n\n"
        "כל מה שאתה צריך לעשות זה להגיד לנו *מה אתה עושה*, ואנחנו נדאג לשאר.\n"
        "לחץ על הכפתור למטה כדי להגדיר את השירותים שאתה מציע:"
    )

    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_add_service = types.InlineKeyboardButton("➕ הוספת תחום התמחות", callback_data="add_service")
    btn_stats = types.InlineKeyboardButton("📊 הסטטיסטיקות שלי", callback_data="menu_stats")

    markup.add(btn_add_service, btn_stats)

    bot.send_message(
        message.chat.id,
        welcome_text,
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ==========================================
# --- ניהול לחיצות על כפתורים ---
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    bot.answer_callback_query(call.id)

    if call.data == "menu_stats":
        show_stats(call.message)

    elif call.data == "add_service":
        ask_for_service(call.message)


# ==========================================
# --- פעולה: הצגת סטטיסטיקות ---
# ==========================================
def show_stats(message):
    msg = bot.send_message(message.chat.id, "⏳ שולף נתונים אישיים ממסד הנתונים...")
    user_chat_id = str(message.chat.id)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM leads WHERE chat_id = %s;", (user_chat_id,))
        total_leads = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM leads WHERE ai_score >= 7 AND chat_id = %s;", (user_chat_id,))
        hot_leads = cursor.fetchone()[0]

        conn.close()

        stats_text = (
            f"📊 *הסטטיסטיקות שלך:*\n\n"
            f"סך הכל לידים שנאספו עבורך: {total_leads}\n"
            f"🔥 לידים רותחים (ציון 7+): {hot_leads}"
        )
        bot.edit_message_text(stats_text, chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown")

    except Exception as e:
        bot.edit_message_text(f"❌ שגיאה בשליפת נתונים: {e}", chat_id=message.chat.id, message_id=msg.message_id)


# ==========================================
# --- פעולה: הוספת שירות ---
# ==========================================
def ask_for_service(message):
    msg = bot.send_message(
        message.chat.id,
        "איזה שירות או טכנולוגיה אתה מציע?\n_(לדוגמה: React, עיצוב לוגו, Shopify, SEO, Python)_\n\n⌨️ הקלד עכשיו את התחום (או שלח /cancel לביטול):",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, process_new_keyword, "context")


def process_new_keyword(message, category):
    if message.text == '/cancel':
        bot.send_message(message.chat.id, "הפעולה בוטלה.")
        return

    word = message.text.lower().strip()
    user_chat_id = str(message.chat.id)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO keywords (word, category, chat_id) VALUES (%s, %s, %s) ON CONFLICT (word, chat_id) DO NOTHING;",
            (word, category, user_chat_id)
        )

        if cursor.rowcount > 0:
            bot.send_message(message.chat.id, f"✅ מעולה! התחום '*{word}*' נוסף בהצלחה למערכת.\nאנחנו נתחיל לסרוק לקוחות שמחפשים את השירות הזה, ונשלח לך לכאן רק לידים רותחים! 🔥", parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, f"⚠️ התחום '*{word}*' כבר מוגדר אצלך במערכת.", parse_mode="Markdown")

        conn.commit()
        conn.close()

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ שגיאה בשמירת הנתונים: {e}")


if __name__ == "__main__":
    # מפעיל את שרת ה-Flask ברקע כדי ש-Render לא יכבה את התוכנה
    threading.Thread(target=run_flask).start()
    # מפעיל את הבוט של טלגרם
    bot.infinity_polling()