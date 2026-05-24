# email_reader/db.py
import psycopg2
import psycopg2.extras

from .config import DbCredentials


def connect(creds: DbCredentials) -> "psycopg2.extensions.connection":
    return psycopg2.connect(
        host=creds.host,
        port=creds.port,
        user=creds.user,
        password=creds.password,
        dbname="mailpoller",
    )


def bootstrap_schema(conn: "psycopg2.extensions.connection") -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS parameters (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id                BIGSERIAL PRIMARY KEY,
                gmail_message_id  TEXT UNIQUE NOT NULL,
                created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                sender            TEXT NOT NULL,
                subject           TEXT NOT NULL,
                content_url       TEXT,
                pdf_path          TEXT,
                pdf_data          BYTEA
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_gmail_id
            ON messages (gmail_message_id)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id                  BIGSERIAL PRIMARY KEY,
                started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at         TIMESTAMPTZ,
                messages_processed  INT NOT NULL DEFAULT 0,
                messages_errored    INT NOT NULL DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS run_messages (
                id                BIGSERIAL PRIMARY KEY,
                run_id            BIGINT NOT NULL REFERENCES runs(id),
                processed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                gmail_message_id  TEXT NOT NULL,
                sender            TEXT NOT NULL,
                subject           TEXT NOT NULL,
                disposition       TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id                 BIGSERIAL PRIMARY KEY,
                sent_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                notification_type  TEXT NOT NULL,
                failure_count      INT NOT NULL
            )
        """)
    conn.commit()


def load_parameters(conn: "psycopg2.extensions.connection") -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM parameters")
        return {row[0]: row[1] for row in cur.fetchall()}


def message_exists(conn: "psycopg2.extensions.connection", gmail_message_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM messages WHERE gmail_message_id = %s",
            (gmail_message_id,),
        )
        return cur.fetchone() is not None


def insert_message(
    conn: "psycopg2.extensions.connection",
    gmail_message_id: str,
    sender: str,
    subject: str,
    content_url: str | None,
    pdf_path: str,
    pdf_data: bytes,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages
                (gmail_message_id, sender, subject, content_url, pdf_path, pdf_data)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (gmail_message_id, sender, subject, content_url, pdf_path,
             psycopg2.Binary(pdf_data)),
        )
    conn.commit()


def insert_run(conn: "psycopg2.extensions.connection") -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO runs (started_at) VALUES (NOW()) RETURNING id")
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT INTO runs returned no id")
        run_id = row[0]
    conn.commit()
    return run_id


def close_run(conn: "psycopg2.extensions.connection", run_id: int, messages_processed: int, messages_errored: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE runs
            SET finished_at = NOW(),
                messages_processed = %s,
                messages_errored   = %s
            WHERE id = %s
            """,
            (messages_processed, messages_errored, run_id),
        )
    conn.commit()


def insert_run_message(
    conn: "psycopg2.extensions.connection",
    run_id: int,
    gmail_message_id: str,
    sender: str,
    subject: str,
    disposition: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO run_messages
                (run_id, gmail_message_id, sender, subject, disposition)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (run_id, gmail_message_id, sender, subject, disposition),
        )
    conn.commit()


def get_today_failed_messages(conn: "psycopg2.extensions.connection", today_sgt_date: str) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT rm.gmail_message_id, rm.sender, rm.subject, m.content_url
            FROM run_messages rm
            LEFT JOIN messages m ON rm.gmail_message_id = m.gmail_message_id
            WHERE rm.disposition = 'failed'
              AND (rm.processed_at AT TIME ZONE 'Asia/Singapore')::date = %s::date
            """,
            (today_sgt_date,),
        )
        return [dict(row) for row in cur.fetchall()]


def digest_sent_today(conn: "psycopg2.extensions.connection", today_sgt_date: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM notification_log
            WHERE notification_type = 'daily_digest'
              AND (sent_at AT TIME ZONE 'Asia/Singapore')::date = %s::date
            """,
            (today_sgt_date,),
        )
        return cur.fetchone() is not None


def insert_notification_log(conn: "psycopg2.extensions.connection", notification_type: str, failure_count: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notification_log (notification_type, failure_count)
            VALUES (%s, %s)
            """,
            (notification_type, failure_count),
        )
    conn.commit()
