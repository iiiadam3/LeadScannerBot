# AI-Powered Lead Aggregation Bot 🎯

A fully autonomous, serverless data pipeline that scans platforms like Reddit, Upwork, and WeWorkRemotely for high-quality freelance leads, evaluates their purchasing intent using an LLM (OpenAI), and delivers real-time notifications via a Telegram Bot.

## 🚀 Key Features
- **Smart Intent Scoring:** Uses the OpenAI API (`gpt-4o-mini`) to process post content and grade buying intent (1-10), filtering out noise, tutorials, and unpaid requests.
- **Dynamic Sourcing:** Dynamically generates RSS queries based on user-defined keywords stored in the database.
- **Idempotency & Multi-Tenancy:** Uses a PostgreSQL database with strict `UNIQUE (link, chat_id)` constraints to manage multiple users and prevent duplicate notifications.
- **Telegram Interface:** Users can easily add/remove context keywords and check their lead statistics via an interactive Telegram Bot.

## 🛠️ Tech Stack & Architecture
- **Backend:** Python, Flask (Webhook integration)
- **Database:** PostgreSQL (Hosted on Supabase)
- **Automation:** Cron-jobs triggering a Python scraper every 30 minutes
- **AI Integration:** OpenAI API
- **Deployment:** Render (Telegram Bot web service), GitHub Actions / Cron-job.org

## 📸 Sneak Peek
<img width="547" height="393" alt="Screenshot 2026-10-12 160934" src="https://github.com/user-attachments/assets/8d68c2f7-77a9-4535-aeda-cb468e5a7ed7" />
<img width="598" height="782" alt="Screenshot 2026-10-13 151323" src="https://github.com/user-attachments/assets/d0f0865d-1a8e-4623-8e80-28c1f381b7a3" />

## ⚙️ How to Run Locally

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/iiiadam3/LeadScannerBot.git](https://github.com/iiiadam3/LeadScannerBot.git)
   cd LeadScannerBot
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up Environment Variables:**
   Create a `.env` file in the root directory and add the following:
   ```env
   TELEGRAM_TOKEN=your_telegram_bot_token
   DATABASE_URL=your_postgresql_database_url
   OPENAI_API_KEY=your_openai_api_key
   ```

4. **Run the Scanner:**
   ```bash
   python LeadScanner.py
   ```
