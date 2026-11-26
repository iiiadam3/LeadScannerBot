"""Schema shared by LeadScanner.py and bot_manager.py.

Both processes call init_schema on the same database, so every statement
here must stay idempotent (IF NOT EXISTS / IF EXISTS).
"""


def init_schema(conn):
    """Idempotent schema setup. Runs inside the caller's connection."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id SERIAL PRIMARY KEY,
                date TEXT,
                title TEXT,
                link TEXT,
                score INTEGER,
                ai_score INTEGER,
                chat_id TEXT,
                CONSTRAINT leads_link_chat_id_key UNIQUE (link, chat_id)
            );
            """
        )
        # One-time cleanup of the legacy single-column constraint (no CASCADE needed).
        cur.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_link_key;")
        # Mirrors the Supabase table; bot_manager.py's ON CONFLICT relies on UNIQUE (word, chat_id).
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS keywords (
                id SERIAL PRIMARY KEY,
                word TEXT,
                category TEXT,
                chat_id TEXT,
                UNIQUE (word, chat_id)
            );
            """
        )
    conn.commit()
