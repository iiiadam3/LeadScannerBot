import os
import logging
from contextlib import closing
import telebot
from telebot import types
import psycopg2
from flask import Flask, request
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)


@app.route('/')
def alive():
    return "Bot is alive!"


@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def webhook():
    # קבלת ההודעה מטלגרם והעברתה לטיפול של הבוט
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "OK", 200


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
    send_main_menu(message.chat.id)


def send_main_menu(chat_id):
    welcome_text = (
        "👋 *ברוך הבא למערכת איתור הלקוחות החכמה!*\n\n"
        "אנחנו סורקים את הרשת 24/7 כדי למצוא יזמים ולקוחות שמחפשים לשלם על שירותים דיגיטליים, "
        "ומעבירים אותם סינון AI כדי לוודא שמדובר בליד רותח.\n\n"
        "כל מה שאתה צריך לעשות זה להגיד לנו *מה אתה עושה*, ואנחנו נדאג לשאר.\n"
        "לחץ על הכפתור למטה כדי להגדיר את השירותים שאתה מציע:"
    )

    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_add_service = types.InlineKeyboardButton("➕ הוספת תחום התמחות", callback_data="add_service")
    btn_manage = types.InlineKeyboardButton("⚙️ ניהול תחומי התמחות", callback_data="manage_services")
    btn_stats = types.InlineKeyboardButton("📊 הסטטיסטיקות שלי", callback_data="menu_stats")

    markup.add(btn_add_service, btn_manage, btn_stats)
    bot.send_message(chat_id, welcome_text, reply_markup=markup, parse_mode="Markdown")


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
    elif call.data == "manage_services":
        show_services_for_management(call.message)
    elif call.data.startswith("del_srv_"):
        delete_service(call)
    elif call.data == "main_menu":
        # מחיקת הודעת הניהול והצגת התפריט הראשי
        bot.delete_message(call.message.chat.id, call.message.message_id)
        send_main_menu(call.message.chat.id)


# ==========================================
# --- פעולה: הצגת סטטיסטיקות ---
# ==========================================
def show_stats(message):
    msg = bot.send_message(message.chat.id, "⏳ שולף נתונים אישיים ממסד הנתונים...")
    user_chat_id = str(message.chat.id)

    try:
        with closing(get_db_connection()) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM leads WHERE chat_id = %s;", (user_chat_id,))
            total_leads = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM leads WHERE ai_score >= 7 AND chat_id = %s;", (user_chat_id,))
            hot_leads = cursor.fetchone()[0]

        stats_text = (
            f"📊 *הסטטיסטיקות שלך:*\n\n"
            f"סך הכל לידים שנאספו עבורך: {total_leads}\n"
            f"🔥 לידים רותחים (ציון 7+): {hot_leads}\n\n"
            f"_(לחץ /start לחזרה לתפריט הראשי)_"
        )
        bot.edit_message_text(stats_text, chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error fetching stats for chat_id {user_chat_id}: {e}")
        bot.edit_message_text(
            "❌ אירעה שגיאה זמנית בשליפת הנתונים. נסה שוב מאוחר יותר.",
            chat_id=message.chat.id,
            message_id=msg.message_id
        )


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
    if not message.text or message.text == '/cancel':
        bot.send_message(message.chat.id, "הפעולה בוטלה.\n_(לחץ /start לחזרה לתפריט הראשי)_", parse_mode="Markdown")
        return

    word = message.text.lower().strip()
    user_chat_id = str(message.chat.id)

    try:
        with closing(get_db_connection()) as conn, conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO keywords (word, category, chat_id) VALUES (%s, %s, %s) ON CONFLICT (word, chat_id) DO NOTHING;",
                (word, category, user_chat_id)
            )
            inserted = cursor.rowcount > 0
            conn.commit()

        if inserted:
            bot.send_message(
                message.chat.id,
                f"✅ מעולה! התחום '*{word}*' נוסף בהצלחה למערכת.\nאנחנו נתחיל לסרוק לקוחות שמחפשים את השירות הזה, ונשלח לך לכאן רק לידים רותחים! 🔥\n\n_(לחץ /start לחזרה לתפריט הראשי)_",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(
                message.chat.id,
                f"⚠️ התחום '*{word}*' כבר מוגדר אצלך במערכת.\n\n_(לחץ /start לחזרה לתפריט הראשי)_",
                parse_mode="Markdown"
            )
    except Exception as e:
        logging.error(f"Error inserting keyword '{word}' for chat_id {user_chat_id}: {e}")
        bot.send_message(message.chat.id, "❌ אירעה שגיאה זמנית בשמירת הנתונים. נסה שוב מאוחר יותר.")


# ==========================================
# --- פעולה: ניהול ומחיקת שירותים ---
# ==========================================
def show_services_for_management(message):
    user_chat_id = str(message.chat.id)
    try:
        with closing(get_db_connection()) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT word FROM keywords WHERE chat_id = %s AND category = 'context';", (user_chat_id,))
            rows = cursor.fetchall()

        markup = types.InlineKeyboardMarkup(row_width=1)
        if not rows:
            bot.send_message(
                message.chat.id,
                "עדיין לא הגדרת תחומי התמחות. לחץ על 'הוספת תחום התמחות' כדי להתחיל.\n\n_(לחץ /start לחזרה)_",
                parse_mode="Markdown"
            )
            return

        for row in rows:
            word = row[0]
            markup.add(types.InlineKeyboardButton(f"🗑️ מחיקה: {word}", callback_data=f"del_srv_{word}"))

        markup.add(types.InlineKeyboardButton("🔙 חזרה לתפריט הראשי", callback_data="main_menu"))

        bot.send_message(
            message.chat.id,
            "⚙️ *ניהול תחומי התמחות*\n\nאלו התחומים שמוגדרים לך כרגע.\nלחץ על כפתור כדי למחוק את התחום ולהפסיק לקבל לידים עבורו:",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Error loading services for chat_id {user_chat_id}: {e}")
        bot.send_message(message.chat.id, "❌ אירעה שגיאה זמנית בשליפת הנתונים. נסה שוב מאוחר יותר.")


def delete_service(call):
    word_to_delete = call.data.replace("del_srv_", "")
    user_chat_id = str(call.message.chat.id)

    try:
        with closing(get_db_connection()) as conn, conn.cursor() as cursor:
            cursor.execute("DELETE FROM keywords WHERE word = %s AND chat_id = %s;", (word_to_delete, user_chat_id))
            conn.commit()

        bot.edit_message_text(
            f"✅ התחום '*{word_to_delete}*' הוסר בהצלחה.\nלא תקבל יותר לידים עבורו.\n\n_(לחץ /start לחזרה לתפריט הראשי)_",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Error deleting keyword '{word_to_delete}' for chat_id {user_chat_id}: {e}")
        bot.send_message(call.message.chat.id, "❌ אירעה שגיאה זמנית במחיקת התחום. נסה שוב מאוחר יותר.")


if __name__ == "__main__":
    run_flask()