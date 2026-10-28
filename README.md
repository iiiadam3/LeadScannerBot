# AI-Powered Lead Aggregation Bot 🎯

An automated, multi-tenant lead aggregation system that scans platforms like Reddit, Upwork, and WeWorkRemotely for high-quality freelance leads, evaluates purchasing intent using an LLM (OpenAI), and delivers real-time notifications via an interactive Telegram Bot.

## 🚀 Key Features
- **Two-Stage Filtering (Regex + LLM):** Performs fast initial filtering using whole-word boundary regular expressions, then uses the OpenAI API (`gpt-4o-mini`) to grade buying intent (1–10), filtering out noise, tutorials, and unpaid requests.
- **Dynamic RSS Sourcing:** Dynamically builds RSS queries based on user-defined keywords stored in PostgreSQL.
- **Idempotency & Multi-Tenancy:** Uses a PostgreSQL database with strict `UNIQUE (link, chat_id)` constraints and `ON CONFLICT DO NOTHING` queries to support multiple users and prevent duplicate notifications.
- **Interactive Telegram Interface:** Users can add/remove service keywords and view real-time lead statistics via an interactive Telegram Bot powered by Flask webhooks.

## 🛠️ Tech Stack & Architecture
- **Bot Webhook Server:** Python, Flask, `pyTelegramBotAPI` (deployed as a Web Service on Render)
- **Scheduled Lead Scanner:** Python worker triggered every 30 minutes via GitHub Actions Cron
- **Database:** PostgreSQL (hosted on Supabase)
- **AI Integration:** OpenAI API (`gpt-4o-mini`)
- **Testing:** `pytest` & `unittest.mock`

## 📸 Sneak Peek
<img width="547" height="393" alt="Screenshot 2026-10-12 160934" src="https://github.com/user-attachments/assets/8d68c2f7-77a9-4535-aeda-cb468e5a7ed7" />
<img width="598" height="782" alt="Screenshot 2026-10-13 151323" src="https://github.com/user-attachments/assets/d0f0865d-1a8e-4623-8e80-28c1f381b7a3" />

## ⚙️ How to Run Locally

1. **Clone the repository:**
   ```bash
   git clone https://github.com/iiiadam3/LeadScannerBot.git
   cd LeadScannerBot
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up Environment Variables:**
   Create a local `.env` file in the root directory (this file is git-ignored) and insert your own API keys:
   ```env
   TELEGRAM_TOKEN=<insert_your_telegram_bot_token>
   DATABASE_URL=<insert_your_postgresql_connection_url>
   OPENAI_API_KEY=<insert_your_openai_api_key>
   ```

4. **Run the Scanner or Bot Server:**
   ```bash
   # Run a single lead scan cycle
   python LeadScanner.py

   # Start the Flask webhook server for the Telegram bot
   python bot_manager.py
   ```

5. **Run Unit Tests:**
   ```bash
   pytest
   ```