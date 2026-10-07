import os
import telebot
from telebot import types
import psycopg2
from dotenv import load_dotenv
from flask import Flask
import threading

load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ==========================================
# --- שרת דמה (Flask) כדי ש-Render לא יכבה את הבוט ---
# ==========================================
app = Flask(__name__)


@app.route('/')
def home():
    return "Bot is awake and running!"


def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


# ==========================================
# --- פונקציית עזר: התחברות למסד הנתונים ---
# ==========================================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


# ==========================================
# --- תפריט ראשי ---
# ==========================================
@bot.message_handler(commands=['start', 'menu', 'help'])
def send_menu(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_stats = types.InlineKeyboardButton("📊 סטטיסטיקות לידים", callback_data="menu_stats")
    btn_add_word = types.InlineKeyboardButton("➕ הוספת מילת מפתח", callback_data="menu_add_word")

    markup.add(btn_stats, btn_add_word)

    bot.send_message(
        message.chat.id,
        "🤖 *ברוך הבא למערכת ניהול הלידים!*\nמה תרצה לעשות היום?",
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

    elif call.data == "menu_add_word":
        ask_for_category(call.message)

    elif call.data.startswith("cat_"):
        category = call.data.split("_")[1]
        ask_for_word(call.message, category)


# ==========================================
# --- פעולה: הצגת סטטיסטיקות ---
# ==========================================
def show_stats(message):
    msg = bot.send_message(message.chat.id, "⏳ שולף נתונים ממסד הנתונים...")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM leads;")
        total_leads = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM leads WHERE ai_score >= 7;")
        hot_leads = cursor.fetchone()[0]

        conn.close()

        stats_text = (
            f"📊 *סטטיסטיקות לידים:*\n\n"
            f"סך הכל לידים שנאספו: {total_leads}\n"
            f"🔥 לידים רותחים (ציון 7+): {hot_leads}"
        )
        bot.edit_message_text(stats_text, chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown")

    except Exception as e:
        bot.edit_message_text(f"❌ שגיאה בשליפת נתונים: {e}", chat_id=message.chat.id, message_id=msg.message_id)


# ==========================================
# --- פעולה: הוספת מילת מפתח ---
# ==========================================
def ask_for_category(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_intent = types.InlineKeyboardButton("Intent (כוונה)", callback_data="cat_intent")
    btn_context = types.InlineKeyboardButton("Context (הקשר)", callback_data="cat_context")
    btn_negative = types.InlineKeyboardButton("Negative (שלילית)", callback_data="cat_negative")

    markup.add(btn_intent, btn_context)
    markup.add(btn_negative)

    bot.send_message(message.chat.id, "לאיזו קטגוריה תרצה להוסיף את המילה?", reply_markup=markup)


def ask_for_word(message, category):
    msg = bot.send_message(message.chat.id,
                           f"בחרת בקטגוריה: *{category}*.\n\n⌨️ אנא הקלד כעת את מילת המפתח (או שלח /cancel לביטול):",
                           parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_new_keyword, category)


def process_new_keyword(message, category):
    if message.text == '/cancel':
        bot.send_message(message.chat.id, "הפעולה בוטלה.")
        return

    word = message.text.lower().strip()
    user_chat_id = str(message.chat.id)  # חילוץ מזהה המשתמש

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # הכנסת המילה יחד עם מזהה המשתמש לטבלה
        cursor.execute(
            "INSERT INTO keywords (word, category, chat_id) VALUES (%s, %s, %s) ON CONFLICT (word, chat_id) DO NOTHING;",
            (word, category, user_chat_id)
        )

        if cursor.rowcount > 0:
            bot.send_message(message.chat.id, f"✅ המילה '{word}' התווספה בהצלחה לקטגוריה {category}!")
        else:
            bot.send_message(message.chat.id, f"⚠️ המילה '{word}' כבר קיימת אצלך במערכת.")

        conn.commit()
        conn.close()

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ שגיאה בשמירת המילה: {e}")


# ==========================================
# --- הרצת הבוט והשרת במקביל ---
# ==========================================
if __name__ == "__main__":
    # הפעלת שרת האינטרנט ברקע
    threading.Thread(target=run_server).start()

    print("Bot is running. Waiting for Telegram messages...")
    bot.infinity_polling()