import hashlib
import logging
import os
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

if not TELEGRAM_TOKEN:
    # Without this the failure was "TypeError: 'NoneType' object is not iterable",
    # which says nothing about the missing setting.
    raise RuntimeError(
        "TELEGRAM_TOKEN is not set. Add it to your .env file locally, "
        "or to the service's environment variables when deploying."
    )

# Telegram rejects callback_data over 64 bytes. A Hebrew keyword costs 2 bytes a letter,
# so the keyword itself cannot be carried in the button; a short digest of it is.
SERVICE_TOKEN_LENGTH = 16
DELETE_PREFIX = "del_srv_"

# Long enough for a real service name, short enough to keep messages readable.
MAX_KEYWORD_LENGTH = 60

# Characters that Telegram's Markdown treats as formatting. Left as typed, a keyword
# such as "node_js" makes the whole message fail to send with a 400.
_MARKDOWN_ESCAPES = str.maketrans({character: "\\" + character for character in "_*`["})

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)


def escape_markdown(text):
    """Make user-supplied text safe to drop into a Markdown message."""
    return str(text).translate(_MARKDOWN_ESCAPES)


def service_token(word):
    """A short, stable id for a keyword, so a button never exceeds Telegram's limit."""
    return hashlib.sha256(word.encode("utf-8")).hexdigest()[:SERVICE_TOKEN_LENGTH]


def webhook_url(base_url):
    """The address Telegram should post updates to."""
    return f"{base_url.rstrip('/')}/{TELEGRAM_TOKEN}"


def configure_webhook(base_url=None):
    """
    Tell Telegram where to send updates.

    This has to run on every deploy: the registration lives on Telegram's side, not
    ours, and a service that moves or is redeployed silently stops receiving anything.
    Render provides RENDER_EXTERNAL_URL automatically; WEBHOOK_URL overrides it.
    """
    base_url = base_url or os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if not base_url:
        logging.warning(
            "No WEBHOOK_URL or RENDER_EXTERNAL_URL set, so Telegram was not told where "
            "to send messages. The bot will not answer until one is configured."
        )
        return False
    try:
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url(base_url))
    except Exception:
        # A failure here must not stop the web service from starting.
        logging.exception("Could not register the webhook with Telegram")
        return False
    logging.info("Webhook registered at %s/<token>", base_url.rstrip("/"))
    return True


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
    elif call.data.startswith(DELETE_PREFIX):
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

    if len(word) > MAX_KEYWORD_LENGTH:
        bot.send_message(
            message.chat.id,
            f"⚠️ התחום ארוך מדי (עד {MAX_KEYWORD_LENGTH} תווים).\nנסו משהו קצר וממוקד, למשל 'עיצוב לוגו'."
            "\n\n_(לחץ /start לחזרה לתפריט הראשי)_",
            parse_mode="Markdown",
        )
        return

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
                f"✅ מעולה! התחום '*{escape_markdown(word)}*' נוסף בהצלחה למערכת.\nאנחנו נתחיל לסרוק לקוחות שמחפשים את השירות הזה, ונשלח לך לכאן רק לידים רותחים! 🔥\n\n_(לחץ /start לחזרה לתפריט הראשי)_",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(
                message.chat.id,
                f"⚠️ התחום '*{escape_markdown(word)}*' כבר מוגדר אצלך במערכת.\n\n_(לחץ /start לחזרה לתפריט הראשי)_",
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
            markup.add(types.InlineKeyboardButton(
                f"🗑️ מחיקה: {word}", callback_data=DELETE_PREFIX + service_token(word)))

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
    token = call.data[len(DELETE_PREFIX):]
    user_chat_id = str(call.message.chat.id)

    try:
        with closing(get_db_connection()) as conn, conn.cursor() as cursor:
            # The button carries a digest, so look up which of this user's keywords it means.
            cursor.execute(
                "SELECT word FROM keywords WHERE chat_id = %s AND category = 'context';",
                (user_chat_id,),
            )
            word_to_delete = next(
                (row[0] for row in cursor.fetchall() if service_token(row[0]) == token), None
            )
            if word_to_delete is None:
                bot.edit_message_text(
                    "⚠️ התחום הזה כבר לא קיים אצלך.\n\n_(לחץ /start לחזרה לתפריט הראשי)_",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode="Markdown",
                )
                return
            cursor.execute("DELETE FROM keywords WHERE word = %s AND chat_id = %s;", (word_to_delete, user_chat_id))
            conn.commit()

        bot.edit_message_text(
            f"✅ התחום '*{escape_markdown(word_to_delete)}*' הוסר בהצלחה.\nלא תקבל יותר לידים עבורו.\n\n_(לחץ /start לחזרה לתפריט הראשי)_",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Error deleting a keyword for chat_id {user_chat_id}: {e}")
        bot.send_message(call.message.chat.id, "❌ אירעה שגיאה זמנית במחיקת התחום. נסה שוב מאוחר יותר.")


# Registered at import time on purpose: under a production server such as gunicorn
# the __main__ block never runs, and the webhook must be set on every deploy.
# With no WEBHOOK_URL/RENDER_EXTERNAL_URL (local use, tests) this only logs a warning.
configure_webhook()


if __name__ == "__main__":
    run_flask()
