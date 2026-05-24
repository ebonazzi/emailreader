# Gmail-to-PDF Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python service that polls a Gmail inbox, converts each message's content (body or linked URL) to a PDF via Playwright/Chromium, stores the PDF on disk and in PostgreSQL, and runs as a systemd timer service limited to 07:00–20:00 Singapore time.

**Architecture:** Modular package (`email_reader/`) with one file per responsibility. `main.py` orchestrates eight focused modules — `config`, `db`, `gmail`, `url_detector`, `pdf`, `run_logger`, `notifier` — in a sequential pipeline. A single Playwright Chromium browser instance is reused across all messages in a run to avoid per-message startup overhead.

**Tech Stack:** Python 3.14, Playwright (Chromium), google-api-python-client, google-auth, psycopg2-binary, beautifulsoup4, lxml, pytz, pytest, systemd.

---

## File Map

| File | Role |
|------|------|
| `pyproject.toml` | Package metadata, entry point `email-reader`, dev deps |
| `requirements.txt` | Pinned deps for venv install |
| `email_reader/__init__.py` | Empty package marker |
| `email_reader/config.py` | Parse 4-line credentials file; `AppConfig` dataclass from DB params dict |
| `email_reader/db.py` | Connect to PostgreSQL; bootstrap schema; all SQL queries |
| `email_reader/gmail.py` | OAuth2 refresh; list/fetch messages; send email; mark as read |
| `email_reader/url_detector.py` | Body-length heuristic; anchor-text URL scoring; blocklist filtering; CID inlining |
| `email_reader/pdf.py` | `PdfRenderer` class wrapping Playwright; URL + body rendering; failure detection |
| `email_reader/run_logger.py` | `RunLogger` class; create/close `runs` rows; append `run_messages` rows |
| `email_reader/notifier.py` | Hourly and daily failure digest logic; `evaluate_and_notify()` |
| `email_reader/main.py` | CLI entry point; operating-window check; pipeline orchestration |
| `tests/__init__.py` | Empty |
| `tests/conftest.py` | Shared `make_config()` helper and common fixtures |
| `tests/test_config.py` | Unit tests for config loading |
| `tests/test_db.py` | Unit tests for DB queries (mocked psycopg2) |
| `tests/test_gmail.py` | Unit tests for Gmail helpers (mocked API) |
| `tests/test_url_detector.py` | Unit tests for detection heuristic (pure logic) |
| `tests/test_pdf.py` | Integration tests for Playwright rendering |
| `tests/test_run_logger.py` | Unit tests for RunLogger (mocked DB) |
| `tests/test_notifier.py` | Unit tests for notification logic (mocked DB + Gmail) |
| `tests/test_main.py` | Unit tests for `is_in_operating_window` and `make_pdf_filename` |
| `systemd/email-reader.service` | oneshot service unit |
| `systemd/email-reader.timer` | Timer unit with `__POLL_INTERVAL__` placeholder |
| `setup.sh` | Deploy script: venv, Playwright browser, systemd unit installation |

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `email_reader/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "email-reader"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "playwright>=1.40",
    "google-api-python-client>=2.100",
    "google-auth>=2.20",
    "psycopg2-binary>=2.9",
    "beautifulsoup4>=4.12",
    "lxml>=4.9",
    "pytz>=2023.3",
]

[project.scripts]
email-reader = "email_reader.main:main"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create requirements.txt**

```
playwright>=1.40
google-api-python-client>=2.100
google-auth>=2.20
psycopg2-binary>=2.9
beautifulsoup4>=4.12
lxml>=4.9
pytz>=2023.3
pytest>=8.0
pytest-cov>=5.0
```

- [ ] **Step 3: Create package and test markers**

```python
# email_reader/__init__.py
# (empty)
```

```python
# tests/__init__.py
# (empty)
```

- [ ] **Step 4: Create tests/conftest.py with shared AppConfig factory**

```python
# tests/conftest.py
from email_reader.config import AppConfig


def make_config(**overrides) -> AppConfig:
    defaults = dict(
        gmail_client_id="test_client_id",
        gmail_client_secret="test_client_secret",
        gmail_refresh_token="test_refresh_token",
        gmail_user="sender@gmail.com",
        pdf_output_dir="/tmp/pdfs",
        mark_read=False,
        url_detection_threshold=500,
        paywall_text_threshold=200,
        url_blocklist=["commonsense-computing.com/efb.html"],
        poll_interval_minutes=30,
        email_failure_send="daily",
        operating_window_start="07:00",
        operating_window_end="20:00",
        daily_digest_time="19:30",
    )
    defaults.update(overrides)
    return AppConfig(**defaults)
```

- [ ] **Step 5: Install the package in development mode**

```bash
cd /home/ebonazzi/PycharmProjects/EmailReader
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

Expected: no errors; `email-reader` command available in PATH.

- [ ] **Step 6: Verify pytest runs (no tests yet)**

```bash
pytest -v
```

Expected: `no tests ran` with exit code 5, or similar empty-suite message.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml requirements.txt email_reader/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: scaffold email_reader package and test suite"
```

---

## Task 2: config.py — Credentials and Parameter Loading

**Files:**
- Create: `email_reader/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
import pytest
from pathlib import Path
from email_reader.config import load_db_credentials, load_app_config, DbCredentials, AppConfig


def test_load_db_credentials_parses_4_lines(tmp_path):
    f = tmp_path / "creds.txt"
    f.write_text("myhost\n5432\nmailpoller\nsecret\n")
    creds = load_db_credentials(str(f))
    assert creds.host == "myhost"
    assert creds.port == 5432
    assert creds.user == "mailpoller"
    assert creds.password == "secret"


def test_load_db_credentials_rejects_wrong_line_count(tmp_path):
    f = tmp_path / "creds.txt"
    f.write_text("onlyoneline\n")
    with pytest.raises(ValueError, match="4 lines"):
        load_db_credentials(str(f))


def test_load_app_config_uses_defaults():
    params = {
        "gmail_client_id": "cid",
        "gmail_client_secret": "csecret",
        "gmail_refresh_token": "rtoken",
        "pdf_output_dir": "/tmp/pdfs",
    }
    config = load_app_config(params)
    assert config.url_detection_threshold == 500
    assert config.paywall_text_threshold == 200
    assert config.mark_read is False
    assert config.email_failure_send == "daily"
    assert config.operating_window_start == "07:00"
    assert config.operating_window_end == "20:00"
    assert config.daily_digest_time == "19:30"
    assert "commonsense-computing.com/efb.html" in config.url_blocklist


def test_load_app_config_mark_read_true():
    params = {
        "gmail_client_id": "cid",
        "gmail_client_secret": "csecret",
        "gmail_refresh_token": "rtoken",
        "pdf_output_dir": "/tmp/pdfs",
        "mark_read": "true",
    }
    config = load_app_config(params)
    assert config.mark_read is True


def test_load_app_config_multiline_blocklist():
    params = {
        "gmail_client_id": "cid",
        "gmail_client_secret": "csecret",
        "gmail_refresh_token": "rtoken",
        "pdf_output_dir": "/tmp/pdfs",
        "url_blocklist": "example.com\nspam.org\n",
    }
    config = load_app_config(params)
    assert "example.com" in config.url_blocklist
    assert "spam.org" in config.url_blocklist


def test_load_app_config_missing_required_key_raises():
    with pytest.raises(KeyError):
        load_app_config({})
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError` — `config` module does not exist yet.

- [ ] **Step 3: Implement email_reader/config.py**

```python
# email_reader/config.py
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DbCredentials:
    host: str
    port: int
    user: str
    password: str


@dataclass(frozen=True)
class AppConfig:
    gmail_client_id: str
    gmail_client_secret: str
    gmail_refresh_token: str
    gmail_user: str
    pdf_output_dir: str
    mark_read: bool
    url_detection_threshold: int
    paywall_text_threshold: int
    url_blocklist: tuple
    poll_interval_minutes: int
    email_failure_send: str
    operating_window_start: str
    operating_window_end: str
    daily_digest_time: str


def load_db_credentials(path: str) -> DbCredentials:
    lines = Path(path).read_text().strip().splitlines()
    if len(lines) != 4:
        raise ValueError(f"Credentials file must have 4 lines, got {len(lines)}")
    host, port, user, password = [ln.strip() for ln in lines]
    return DbCredentials(host=host, port=int(port), user=user, password=password)


def load_app_config(params: dict) -> AppConfig:
    raw_blocklist = params.get(
        "url_blocklist", "commonsense-computing.com/efb.html"
    )
    blocklist = tuple(
        line.strip() for line in raw_blocklist.splitlines() if line.strip()
    )
    return AppConfig(
        gmail_client_id=params["gmail_client_id"],
        gmail_client_secret=params["gmail_client_secret"],
        gmail_refresh_token=params["gmail_refresh_token"],
        gmail_user=params.get("gmail_user", "bumbojavalovernet@gmail.com"),
        pdf_output_dir=params["pdf_output_dir"],
        mark_read=params.get("mark_read", "false").lower() == "true",
        url_detection_threshold=int(params.get("url_detection_threshold", "500")),
        paywall_text_threshold=int(params.get("paywall_text_threshold", "200")),
        url_blocklist=blocklist,
        poll_interval_minutes=int(params.get("poll_interval_minutes", "30")),
        email_failure_send=params.get("email_failure_send", "daily"),
        operating_window_start=params.get("operating_window_start", "07:00"),
        operating_window_end=params.get("operating_window_end", "20:00"),
        daily_digest_time=params.get("daily_digest_time", "19:30"),
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 6 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add email_reader/config.py tests/test_config.py
git commit -m "feat: add config module with DbCredentials and AppConfig loading"
```

---

## Task 3: db.py — PostgreSQL Schema and Queries

**Files:**
- Create: `email_reader/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db.py
import pytest
from unittest.mock import MagicMock, patch
from email_reader.db import (
    bootstrap_schema,
    load_parameters,
    message_exists,
    insert_message,
    insert_run,
    close_run,
    insert_run_message,
    digest_sent_today,
    insert_notification_log,
)


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


def test_bootstrap_schema_executes_five_statements(mock_conn):
    conn, cursor = mock_conn
    bootstrap_schema(conn)
    assert cursor.execute.call_count == 6  # 5 CREATE TABLE + 1 CREATE INDEX
    conn.commit.assert_called_once()


def test_load_parameters_returns_dict(mock_conn):
    conn, cursor = mock_conn
    cursor.fetchall.return_value = [("key1", "val1"), ("key2", "val2")]
    result = load_parameters(conn)
    assert result == {"key1": "val1", "key2": "val2"}


def test_message_exists_true(mock_conn):
    conn, cursor = mock_conn
    cursor.fetchone.return_value = (1,)
    assert message_exists(conn, "msg123") is True


def test_message_exists_false(mock_conn):
    conn, cursor = mock_conn
    cursor.fetchone.return_value = None
    assert message_exists(conn, "msg123") is False


def test_insert_run_returns_generated_id(mock_conn):
    conn, cursor = mock_conn
    cursor.fetchone.return_value = (42,)
    run_id = insert_run(conn)
    assert run_id == 42
    conn.commit.assert_called_once()


def test_close_run_updates_row(mock_conn):
    conn, cursor = mock_conn
    close_run(conn, run_id=42, messages_processed=3, messages_errored=1)
    cursor.execute.assert_called_once()
    args = cursor.execute.call_args[0]
    assert "UPDATE runs" in args[0]
    assert args[1] == (3, 1, 42)
    conn.commit.assert_called_once()


def test_insert_run_message_inserts_row(mock_conn):
    conn, cursor = mock_conn
    insert_run_message(conn, run_id=1, gmail_message_id="abc", sender="a@b.com",
                       subject="Hello", disposition="url_rendered")
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_digest_sent_today_true(mock_conn):
    conn, cursor = mock_conn
    cursor.fetchone.return_value = (1,)
    assert digest_sent_today(conn, "2026-05-24") is True


def test_digest_sent_today_false(mock_conn):
    conn, cursor = mock_conn
    cursor.fetchone.return_value = None
    assert digest_sent_today(conn, "2026-05-24") is False


def test_insert_notification_log_inserts_row(mock_conn):
    conn, cursor = mock_conn
    insert_notification_log(conn, "daily_digest", 5)
    cursor.execute.assert_called_once()
    args = cursor.execute.call_args[0]
    assert args[1] == ("daily_digest", 5)
    conn.commit.assert_called_once()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_db.py -v
```

Expected: `ImportError` — `db` module does not exist yet.

- [ ] **Step 3: Implement email_reader/db.py**

```python
# email_reader/db.py
from typing import Optional
import psycopg2
import psycopg2.extras
from .config import DbCredentials


def connect(creds: DbCredentials):
    return psycopg2.connect(
        host=creds.host,
        port=creds.port,
        user=creds.user,
        password=creds.password,
        dbname="mailpoller",
    )


def bootstrap_schema(conn) -> None:
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


def load_parameters(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM parameters")
        return {row[0]: row[1] for row in cur.fetchall()}


def message_exists(conn, gmail_message_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM messages WHERE gmail_message_id = %s",
            (gmail_message_id,),
        )
        return cur.fetchone() is not None


def insert_message(
    conn,
    gmail_message_id: str,
    sender: str,
    subject: str,
    content_url: Optional[str],
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


def insert_run(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO runs (started_at) VALUES (NOW()) RETURNING id")
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def close_run(conn, run_id: int, messages_processed: int, messages_errored: int) -> None:
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
    conn,
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


def get_today_failed_messages(conn, today_sgt_date: str) -> list:
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


def digest_sent_today(conn, today_sgt_date: str) -> bool:
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


def insert_notification_log(conn, notification_type: str, failure_count: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notification_log (notification_type, failure_count)
            VALUES (%s, %s)
            """,
            (notification_type, failure_count),
        )
    conn.commit()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_db.py -v
```

Expected: 10 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add email_reader/db.py tests/test_db.py
git commit -m "feat: add db module with schema bootstrap and all SQL queries"
```

---

## Task 4: gmail.py — OAuth2 and Message Handling

**Files:**
- Create: `email_reader/gmail.py`
- Create: `tests/test_gmail.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gmail.py
import base64
import pytest
from unittest.mock import MagicMock, patch
from email_reader.gmail import (
    extract_body_html,
    get_header,
    mark_as_read,
    send_email,
)


def _encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def make_message(html: str, extra_headers: list = None) -> dict:
    headers = [
        {"name": "From", "value": "sender@example.com"},
        {"name": "Subject", "value": "Test Subject"},
    ]
    if extra_headers:
        headers.extend(extra_headers)
    return {
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": headers,
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _encoded(html)},
                    "headers": [],
                }
            ],
        }
    }


def test_extract_body_html_returns_html_content():
    msg = make_message("<p>Hello world</p>")
    html, cids = extract_body_html(msg)
    assert "<p>Hello world</p>" in html
    assert cids == {}


def test_extract_body_html_handles_flat_html_payload():
    encoded = _encoded("<p>Flat</p>")
    msg = {
        "payload": {
            "mimeType": "text/html",
            "headers": [],
            "body": {"data": encoded},
        }
    }
    html, cids = extract_body_html(msg)
    assert "<p>Flat</p>" in html


def test_extract_body_html_returns_empty_for_no_html_part():
    msg = {
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _encoded("plain text")},
                    "headers": [],
                }
            ],
        }
    }
    html, cids = extract_body_html(msg)
    assert html == ""


def test_extract_body_html_inlines_cid_attachment():
    img_data = base64.urlsafe_b64encode(b"\x89PNG").decode()
    msg = {
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [],
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _encoded("<img src='cid:img001'>")},
                    "headers": [],
                },
                {
                    "mimeType": "image/png",
                    "body": {"data": img_data},
                    "headers": [{"name": "Content-Id", "value": "<img001>"}],
                },
            ],
        }
    }
    html, cids = extract_body_html(msg)
    assert "img001" in cids
    assert len(cids["img001"]) > 0


def test_get_header_returns_value():
    msg = make_message("<p>hi</p>")
    assert get_header(msg, "From") == "sender@example.com"
    assert get_header(msg, "Subject") == "Test Subject"


def test_get_header_case_insensitive():
    msg = make_message("<p>hi</p>")
    assert get_header(msg, "from") == "sender@example.com"


def test_get_header_missing_returns_empty():
    msg = make_message("<p>hi</p>")
    assert get_header(msg, "X-Nonexistent") == ""


def test_mark_as_read_removes_unread_label():
    service = MagicMock()
    mark_as_read(service, "msg123")
    service.users().messages().modify.assert_called_once_with(
        userId="me",
        id="msg123",
        body={"removeLabelIds": ["UNREAD"]},
    )


def test_send_email_calls_gmail_api():
    service = MagicMock()
    send_email(service, "from@gmail.com", "to@gmail.com", "Subject", "Body text")
    service.users().messages().send.assert_called_once()
    call_kwargs = service.users().messages().send.call_args[1]
    assert call_kwargs["userId"] == "me"
    assert "raw" in call_kwargs["body"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_gmail.py -v
```

Expected: `ImportError` — `gmail` module does not exist yet.

- [ ] **Step 3: Implement email_reader/gmail.py**

```python
# email_reader/gmail.py
import base64
import logging
from email.mime.text import MIMEText
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def build_gmail_service(client_id: str, client_secret: str, refresh_token: str):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=_SCOPES,
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def list_inbox_messages(service, mark_read: bool) -> list:
    query = "in:inbox is:unread" if mark_read else "in:inbox"
    result = service.users().messages().list(userId="me", q=query).execute()
    return result.get("messages", [])


def fetch_message(service, msg_id: str) -> dict:
    return service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()


def extract_body_html(message: dict) -> tuple:
    """Return (html_body: str, cid_map: dict[str, bytes])."""
    payload = message.get("payload", {})
    html_body = ""
    cid_map: dict = {}

    def _decode(data: str) -> str:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    def _decode_bytes(data: str) -> bytes:
        return base64.urlsafe_b64decode(data + "==")

    def walk(parts: list) -> None:
        nonlocal html_body
        for part in parts:
            mime = part.get("mimeType", "")
            body = part.get("body", {})
            data = body.get("data", "")
            sub_parts = part.get("parts", [])

            if mime == "text/html" and data and not html_body:
                html_body = _decode(data)
            elif mime.startswith("image/") and data:
                headers = {
                    h["name"].lower(): h["value"]
                    for h in part.get("headers", [])
                }
                cid = headers.get("content-id", "").strip("<>")
                if cid:
                    cid_map[cid] = _decode_bytes(data)

            if sub_parts:
                walk(sub_parts)

    if "parts" in payload:
        walk(payload["parts"])
    elif payload.get("mimeType") == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html_body = _decode(data)

    return html_body, cid_map


def get_header(message: dict, name: str) -> str:
    headers = message.get("payload", {}).get("headers", [])
    name_lower = name.lower()
    for h in headers:
        if h["name"].lower() == name_lower:
            return h["value"]
    return ""


def mark_as_read(service, msg_id: str) -> None:
    service.users().messages().modify(
        userId="me",
        id=msg_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()


def send_email(service, from_addr: str, to_addr: str, subject: str, body: str) -> None:
    msg = MIMEText(body)
    msg["to"] = to_addr
    msg["from"] = from_addr
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_gmail.py -v
```

Expected: 10 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add email_reader/gmail.py tests/test_gmail.py
git commit -m "feat: add gmail module with OAuth2, message fetch, and send helpers"
```

---

## Task 5: url_detector.py — Content Detection Heuristic

**Files:**
- Create: `email_reader/url_detector.py`
- Create: `tests/test_url_detector.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_url_detector.py
import pytest
from email_reader.url_detector import (
    visible_text_length,
    is_blocked,
    score_links,
    inline_cid_images,
    wrap_html,
    detect_content,
)

_MIXED_HTML = (
    '<p>See <a href="https://article.com">Read this important geopolitics piece</a>'
    ' and <a href="https://unsubscribe.com">Unsubscribe</a></p>'
)


def test_visible_text_length_counts_text_only():
    assert visible_text_length("<p>Hello world</p>") == 11


def test_visible_text_length_excludes_tags():
    length = visible_text_length("<div><p>One</p><p>Two</p></div>")
    assert length == 7  # "One Two" (space-separated)


def test_is_blocked_matches_substring():
    assert is_blocked("https://example.com/page", ["example.com"]) is True


def test_is_blocked_no_match():
    assert is_blocked("https://good.com/page", ["example.com"]) is False


def test_is_blocked_empty_list():
    assert is_blocked("https://any.com", []) is False


def test_score_links_picks_highest_anchor_text():
    links = score_links(_MIXED_HTML, blocklist=[])
    # "Read this important geopolitics piece" is longer than "Unsubscribe"
    assert links[0][0] == "https://article.com"


def test_score_links_excludes_blocked_urls():
    links = score_links(_MIXED_HTML, blocklist=["unsubscribe.com"])
    hrefs = [link[0] for link in links]
    assert "https://unsubscribe.com" not in hrefs


def test_score_links_excludes_non_http_hrefs():
    html = '<a href="mailto:foo@bar.com">Email me</a><a href="https://ok.com">Click</a>'
    links = score_links(html, blocklist=[])
    assert all(link[0].startswith("http") for link in links)
    assert len(links) == 1


def test_detect_content_url_mode_for_short_body():
    html = '<p>See <a href="https://article.com">Read this important geopolitics piece</a></p>'
    result = detect_content(html, {}, url_detection_threshold=500, blocklist=[])
    assert result.source == "url"
    assert result.url == "https://article.com"


def test_detect_content_body_mode_for_long_body():
    long_body = "<p>" + ("word " * 200) + "</p>"
    result = detect_content(long_body, {}, url_detection_threshold=500, blocklist=[])
    assert result.source == "body"
    assert result.url is None
    assert "<!DOCTYPE html>" in result.html


def test_detect_content_falls_back_to_body_when_all_links_blocked():
    html = '<p>See <a href="https://blocked.com">Read article here now</a></p>'
    result = detect_content(html, {}, url_detection_threshold=500, blocklist=["blocked.com"])
    assert result.source == "body"


def test_inline_cid_images_replaces_src():
    html = '<img src="cid:image001">'
    cid_map = {"image001": b"\x89PNG\r\n"}
    result = inline_cid_images(html, cid_map)
    assert "cid:image001" not in result
    assert "data:image/png;base64," in result


def test_wrap_html_produces_standalone_document():
    wrapped = wrap_html("<p>Content</p>")
    assert "<!DOCTYPE html>" in wrapped
    assert "<p>Content</p>" in wrapped
    assert 'charset="utf-8"' in wrapped
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_url_detector.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement email_reader/url_detector.py**

```python
# email_reader/url_detector.py
import base64
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup


@dataclass
class ContentResult:
    source: str          # "url" or "body"
    url: Optional[str]
    html: str            # prepared HTML ready for Playwright


def visible_text_length(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    return len(soup.get_text(separator=" ", strip=True))


def is_blocked(url: str, blocklist) -> bool:
    return any(blocked in url for blocked in blocklist)


def score_links(html: str, blocklist) -> list:
    """Return [(href, anchor_text, score), ...] sorted by score descending."""
    soup = BeautifulSoup(html, "lxml")
    results = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href.startswith("http"):
            continue
        if is_blocked(href, blocklist):
            continue
        anchor = tag.get_text(strip=True)
        results.append((href, anchor, len(anchor)))
    return sorted(results, key=lambda x: x[2], reverse=True)


def inline_cid_images(html: str, cid_map: dict) -> str:
    result = html
    for cid, data in cid_map.items():
        b64 = base64.b64encode(data).decode()
        data_uri = f"data:image/png;base64,{b64}"
        result = result.replace(f"cid:{cid}", data_uri)
    return result


def wrap_html(body_html: str) -> str:
    return (
        '<!DOCTYPE html>\n'
        '<html><head><meta charset="utf-8">\n'
        '<style>body{font-family:sans-serif;max-width:900px;margin:auto;padding:2rem}</style>\n'
        f'</head><body>{body_html}</body></html>'
    )


def detect_content(
    html: str,
    cid_map: dict,
    url_detection_threshold: int,
    blocklist,
) -> ContentResult:
    text_len = visible_text_length(html)

    if text_len < url_detection_threshold:
        links = score_links(html, blocklist)
        if links:
            best_url = links[0][0]
            return ContentResult(source="url", url=best_url, html=html)

    inlined = inline_cid_images(html, cid_map)
    wrapped = wrap_html(inlined)
    return ContentResult(source="body", url=None, html=wrapped)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_url_detector.py -v
```

Expected: 13 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add email_reader/url_detector.py tests/test_url_detector.py
git commit -m "feat: add url_detector with anchor-text scoring and blocklist filtering"
```

---

## Task 6: pdf.py — Playwright PDF Rendering

**Files:**
- Create: `email_reader/pdf.py`
- Create: `tests/test_pdf.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pdf.py
import pytest
from email_reader.pdf import PdfRenderer, RenderError

LONG_HTML = (
    "<!DOCTYPE html><html><body><h1>Test Document</h1><p>"
    + ("This is content text for the document. " * 20)
    + "</p></body></html>"
)

SHORT_HTML = "<!DOCTYPE html><html><body><p>Login</p></body></html>"

LOGIN_HTML = (
    "<!DOCTYPE html><html><body>"
    '<form><input type="password" name="pw"><button>Sign in</button></form>'
    "</body></html>"
)


@pytest.fixture(scope="module")
def renderer():
    r = PdfRenderer(paywall_text_threshold=100)
    r.open()
    yield r
    r.close()


def test_render_html_returns_pdf_bytes(renderer):
    pdf = renderer.render_html(LONG_HTML)
    assert isinstance(pdf, bytes)
    assert len(pdf) > 0
    assert pdf[:4] == b"%PDF"


def test_render_html_raises_render_error_on_short_content(renderer):
    with pytest.raises(RenderError) as exc_info:
        renderer.render_html(SHORT_HTML)
    assert "paywall" in exc_info.value.reason


def test_render_html_raises_render_error_on_login_form(renderer):
    with pytest.raises(RenderError) as exc_info:
        renderer.render_html(LOGIN_HTML)
    assert "login form" in exc_info.value.reason


def test_render_error_has_reason_attribute():
    err = RenderError("timeout")
    assert err.reason == "timeout"
    assert "timeout" in str(err)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_pdf.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement email_reader/pdf.py**

```python
# email_reader/pdf.py
import logging
from typing import Optional

from playwright.sync_api import (
    Browser,
    Page,
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)

log = logging.getLogger(__name__)


class RenderError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class PdfRenderer:
    def __init__(self, paywall_text_threshold: int):
        self._threshold = paywall_text_threshold
        self._pw = None
        self._browser: Optional[Browser] = None

    def open(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def render_url(self, url: str) -> bytes:
        page = self._browser.new_page()
        try:
            bad_statuses: list = []
            page.on(
                "response",
                lambda r: bad_statuses.append(r.status)
                if r.url == url and r.status >= 400
                else None,
            )
            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
            except PlaywrightTimeout:
                raise RenderError("timeout")
            except Exception as exc:
                raise RenderError(f"network error: {exc}")

            if bad_statuses:
                raise RenderError(f"http {bad_statuses[0]}")

            self._check_page_content(page)
            pdf = page.pdf(format="A4", print_background=True)
            if not pdf:
                raise RenderError("empty pdf")
            return pdf
        finally:
            page.close()

    def render_html(self, html: str) -> bytes:
        page = self._browser.new_page()
        try:
            page.set_content(html, wait_until="networkidle")
            self._check_page_content(page)
            pdf = page.pdf(format="A4", print_background=True)
            if not pdf:
                raise RenderError("empty pdf")
            return pdf
        except RenderError:
            raise
        except Exception as exc:
            raise RenderError(f"playwright error: {exc}")
        finally:
            page.close()

    def _check_page_content(self, page: Page) -> None:
        has_password = page.locator('input[type="password"]').count() > 0
        if has_password:
            raise RenderError("login form detected")
        text = page.evaluate("() => document.body.innerText") or ""
        if len(text.strip()) < self._threshold:
            raise RenderError(
                f"paywall suspected: only {len(text.strip())} chars visible"
            )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_pdf.py -v
```

Expected: 4 tests PASSED. (Playwright will launch a real Chromium browser for these.)

- [ ] **Step 5: Commit**

```bash
git add email_reader/pdf.py tests/test_pdf.py
git commit -m "feat: add pdf module with Playwright rendering and failure detection"
```

---

## Task 7: run_logger.py — Run and Message Logging

**Files:**
- Create: `email_reader/run_logger.py`
- Create: `tests/test_run_logger.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_run_logger.py
import pytest
from unittest.mock import MagicMock, patch
from email_reader.run_logger import RunLogger


@pytest.fixture
def mock_conn():
    return MagicMock()


def test_run_logger_creates_run_on_init(mock_conn):
    with patch("email_reader.run_logger.insert_run", return_value=7) as mock_insert:
        logger = RunLogger(mock_conn)
    assert logger.run_id == 7
    mock_insert.assert_called_once_with(mock_conn)


def test_run_logger_counts_non_skipped_as_processed(mock_conn):
    with patch("email_reader.run_logger.insert_run", return_value=1), \
         patch("email_reader.run_logger.insert_run_message"), \
         patch("email_reader.run_logger.close_run") as mock_close:
        logger = RunLogger(mock_conn)
        logger.log_message("id1", "a@b.com", "Subj1", "url_rendered")
        logger.log_message("id2", "c@d.com", "Subj2", "body_rendered")
        logger.log_message("id3", "e@f.com", "Subj3", "skipped")
        logger.finish()
    # processed=2, errored=0
    mock_close.assert_called_once_with(mock_conn, 1, 2, 0)


def test_run_logger_counts_failed_in_both_counters(mock_conn):
    with patch("email_reader.run_logger.insert_run", return_value=2), \
         patch("email_reader.run_logger.insert_run_message"), \
         patch("email_reader.run_logger.close_run") as mock_close:
        logger = RunLogger(mock_conn)
        logger.log_message("id1", "a@b.com", "Subj1", "url_rendered")
        logger.log_message("id2", "c@d.com", "Subj2", "failed")
        logger.finish()
    # processed=2, errored=1
    mock_close.assert_called_once_with(mock_conn, 2, 2, 1)


def test_run_logger_calls_insert_run_message(mock_conn):
    with patch("email_reader.run_logger.insert_run", return_value=5), \
         patch("email_reader.run_logger.insert_run_message") as mock_insert, \
         patch("email_reader.run_logger.close_run"):
        logger = RunLogger(mock_conn)
        logger.log_message("msgABC", "x@y.com", "Hello", "body_rendered")
    mock_insert.assert_called_once_with(
        mock_conn, 5, "msgABC", "x@y.com", "Hello", "body_rendered"
    )


def test_run_logger_finish_calls_close_run(mock_conn):
    with patch("email_reader.run_logger.insert_run", return_value=9), \
         patch("email_reader.run_logger.close_run") as mock_close:
        logger = RunLogger(mock_conn)
        logger.finish()
    mock_close.assert_called_once_with(mock_conn, 9, 0, 0)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_run_logger.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement email_reader/run_logger.py**

```python
# email_reader/run_logger.py
import logging
from .db import close_run, insert_run, insert_run_message

log = logging.getLogger(__name__)


class RunLogger:
    def __init__(self, conn):
        self._conn = conn
        self._run_id: int = insert_run(conn)
        self._processed = 0
        self._errored = 0

    @property
    def run_id(self) -> int:
        return self._run_id

    def log_message(
        self,
        gmail_message_id: str,
        sender: str,
        subject: str,
        disposition: str,
    ) -> None:
        insert_run_message(
            self._conn, self._run_id, gmail_message_id, sender, subject, disposition
        )
        if disposition != "skipped":
            self._processed += 1
        if disposition == "failed":
            self._errored += 1

    def finish(self) -> None:
        close_run(self._conn, self._run_id, self._processed, self._errored)
        log.info(
            "Run %d complete: %d processed, %d errored",
            self._run_id, self._processed, self._errored,
        )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_run_logger.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add email_reader/run_logger.py tests/test_run_logger.py
git commit -m "feat: add run_logger module tracking processed/errored counts per run"
```

---

## Task 8: notifier.py — Failure Notification Logic

**Files:**
- Create: `email_reader/notifier.py`
- Create: `tests/test_notifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_notifier.py
import pytest
from datetime import datetime, timezone
from unittest.mock import ANY, MagicMock, patch
from tests.conftest import make_config
from email_reader.notifier import (
    FailureRecord,
    evaluate_and_notify,
    _parse_hhmm,
    _build_hourly_body,
    _build_daily_body,
)


def test_parse_hhmm():
    assert _parse_hhmm("07:00") == (7, 0)
    assert _parse_hhmm("19:30") == (19, 30)


def test_build_hourly_body_lists_all_failures():
    failures = [
        FailureRecord("id1", "a@b.com", "Article", "https://example.com", "timeout"),
        FailureRecord("id2", "c@d.com", "Post", None, "http 403"),
    ]
    body = _build_hourly_body(failures)
    assert "id1" in body
    assert "timeout" in body
    assert "https://example.com" in body
    assert "id2" in body
    assert "http 403" in body


def test_build_daily_body_lists_db_rows():
    rows = [
        {"gmail_message_id": "id1", "sender": "a@b.com", "subject": "Art",
         "content_url": "https://example.com"},
    ]
    body = _build_daily_body(rows)
    assert "id1" in body
    assert "https://example.com" in body


# 10:00 SGT = 02:00 UTC
_INSIDE_WINDOW = datetime(2026, 5, 24, 2, 0, 0, tzinfo=timezone.utc)
# 19:45 SGT = 11:45 UTC — past digest time of 19:30
_PAST_DIGEST = datetime(2026, 5, 24, 11, 45, 0, tzinfo=timezone.utc)
# 10:00 SGT = 02:00 UTC — before digest time
_BEFORE_DIGEST = datetime(2026, 5, 24, 2, 0, 0, tzinfo=timezone.utc)


def test_hourly_mode_sends_when_failures():
    config = make_config(email_failure_send="hourly")
    failures = [FailureRecord("id1", "a@b.com", "Subj", None, "timeout")]
    with patch("email_reader.notifier.send_email") as mock_send, \
         patch("email_reader.notifier.insert_notification_log") as mock_log:
        evaluate_and_notify(MagicMock(), MagicMock(), config, failures, _INSIDE_WINDOW)
    mock_send.assert_called_once()
    mock_log.assert_called_once_with(ANY, "hourly_failures", 1)


def test_hourly_mode_silent_when_no_failures():
    config = make_config(email_failure_send="hourly")
    with patch("email_reader.notifier.send_email") as mock_send:
        evaluate_and_notify(MagicMock(), MagicMock(), config, [], _INSIDE_WINDOW)
    mock_send.assert_not_called()


def test_daily_mode_sends_digest_past_digest_time():
    config = make_config(email_failure_send="daily", daily_digest_time="19:30")
    db_rows = [{"gmail_message_id": "id1", "sender": "a@b.com",
                "subject": "Art", "content_url": None}]
    with patch("email_reader.notifier.digest_sent_today", return_value=False), \
         patch("email_reader.notifier.get_today_failed_messages", return_value=db_rows), \
         patch("email_reader.notifier.send_email") as mock_send, \
         patch("email_reader.notifier.insert_notification_log") as mock_log:
        evaluate_and_notify(MagicMock(), MagicMock(), config, [], _PAST_DIGEST)
    mock_send.assert_called_once()
    mock_log.assert_called_once_with(ANY, "daily_digest", 1)


def test_daily_mode_silent_before_digest_time():
    config = make_config(email_failure_send="daily", daily_digest_time="19:30")
    with patch("email_reader.notifier.digest_sent_today", return_value=False), \
         patch("email_reader.notifier.send_email") as mock_send:
        evaluate_and_notify(MagicMock(), MagicMock(), config, [], _BEFORE_DIGEST)
    mock_send.assert_not_called()


def test_daily_mode_silent_if_already_sent_today():
    config = make_config(email_failure_send="daily")
    with patch("email_reader.notifier.digest_sent_today", return_value=True), \
         patch("email_reader.notifier.send_email") as mock_send:
        evaluate_and_notify(MagicMock(), MagicMock(), config, [], _PAST_DIGEST)
    mock_send.assert_not_called()


def test_daily_mode_records_no_op_when_no_failures():
    config = make_config(email_failure_send="daily", daily_digest_time="19:30")
    with patch("email_reader.notifier.digest_sent_today", return_value=False), \
         patch("email_reader.notifier.get_today_failed_messages", return_value=[]), \
         patch("email_reader.notifier.send_email") as mock_send, \
         patch("email_reader.notifier.insert_notification_log") as mock_log:
        evaluate_and_notify(MagicMock(), MagicMock(), config, [], _PAST_DIGEST)
    mock_send.assert_not_called()
    mock_log.assert_called_once_with(ANY, "daily_digest", 0)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_notifier.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement email_reader/notifier.py**

```python
# email_reader/notifier.py
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pytz

from .config import AppConfig
from .db import digest_sent_today, get_today_failed_messages, insert_notification_log
from .gmail import send_email

log = logging.getLogger(__name__)
_SGT = pytz.timezone("Asia/Singapore")


@dataclass
class FailureRecord:
    gmail_message_id: str
    sender: str
    subject: str
    url: Optional[str]
    reason: str


def _parse_hhmm(hhmm: str) -> tuple:
    h, m = hhmm.split(":")
    return int(h), int(m)


def _build_hourly_body(failures: list) -> str:
    lines = ["The following messages could not be processed:\n"]
    for f in failures:
        lines += [
            f"  Gmail ID : {f.gmail_message_id}",
            f"  Sender   : {f.sender}",
            f"  Subject  : {f.subject}",
        ]
        if f.url:
            lines.append(f"  URL      : {f.url}")
        lines += [f"  Reason   : {f.reason}", ""]
    return "\n".join(lines)


def _build_daily_body(rows: list) -> str:
    lines = ["Daily failure digest:\n"]
    for row in rows:
        lines += [
            f"  Gmail ID : {row['gmail_message_id']}",
            f"  Sender   : {row['sender']}",
            f"  Subject  : {row['subject']}",
        ]
        if row.get("content_url"):
            lines.append(f"  URL      : {row['content_url']}")
        lines.append("")
    return "\n".join(lines)


def evaluate_and_notify(
    conn,
    service,
    config: AppConfig,
    run_failures: list,
    now_utc: datetime,
) -> None:
    sgt_now = now_utc.astimezone(_SGT)
    today_str = sgt_now.strftime("%Y-%m-%d")

    if config.email_failure_send == "hourly":
        if not run_failures:
            return
        body = _build_hourly_body(run_failures)
        send_email(
            service, config.gmail_user, "eliobonazzi@gmail.com",
            f"Email Reader: {len(run_failures)} failure(s)", body,
        )
        insert_notification_log(conn, "hourly_failures", len(run_failures))
        log.info("Sent hourly failure notification: %d failures", len(run_failures))

    elif config.email_failure_send == "daily":
        if digest_sent_today(conn, today_str):
            return
        digest_h, digest_m = _parse_hhmm(config.daily_digest_time)
        current_minutes = sgt_now.hour * 60 + sgt_now.minute
        digest_minutes = digest_h * 60 + digest_m
        if current_minutes < digest_minutes:
            return
        failures = get_today_failed_messages(conn, today_str)
        if not failures:
            insert_notification_log(conn, "daily_digest", 0)
            return
        body = _build_daily_body(failures)
        send_email(
            service, config.gmail_user, "eliobonazzi@gmail.com",
            f"Email Reader: daily failure digest ({len(failures)} failures)", body,
        )
        insert_notification_log(conn, "daily_digest", len(failures))
        log.info("Sent daily digest: %d failures", len(failures))
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_notifier.py -v
```

Expected: 9 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add email_reader/notifier.py tests/test_notifier.py
git commit -m "feat: add notifier with hourly and daily SGT-windowed failure digest"
```

---

## Task 9: main.py — Pipeline Orchestration

**Files:**
- Create: `email_reader/main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_main.py
import pytest
from datetime import datetime, timezone
from tests.conftest import make_config
from email_reader.main import is_in_operating_window, make_pdf_filename


# Timezone note: SGT = UTC+8
# 10:00 SGT = 02:00 UTC  → inside 07:00–20:00 window
# 06:00 SGT = 22:00 UTC previous day → before window
# 20:00 SGT = 12:00 UTC → at end boundary (exclusive)


def test_inside_operating_window():
    now = datetime(2026, 5, 24, 2, 0, 0, tzinfo=timezone.utc)  # 10:00 SGT
    assert is_in_operating_window(make_config(), now) is True


def test_before_operating_window():
    now = datetime(2026, 5, 23, 22, 0, 0, tzinfo=timezone.utc)  # 06:00 SGT
    assert is_in_operating_window(make_config(), now) is False


def test_at_operating_window_end_is_excluded():
    now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)  # exactly 20:00 SGT
    assert is_in_operating_window(make_config(), now) is False


def test_just_before_operating_window_end():
    now = datetime(2026, 5, 24, 11, 59, 0, tzinfo=timezone.utc)  # 19:59 SGT
    assert is_in_operating_window(make_config(), now) is True


def test_make_pdf_filename_format():
    now = datetime(2026, 5, 24, 2, 0, 0, tzinfo=timezone.utc)
    name = make_pdf_filename("newsletter@example.com", "The Future of NATO", now)
    assert name.startswith("20260524_newsletter_")
    assert name.endswith(".pdf")
    assert "nato" in name
    assert "future" in name


def test_make_pdf_filename_sanitizes_special_characters():
    now = datetime(2026, 5, 24, 2, 0, 0, tzinfo=timezone.utc)
    name = make_pdf_filename("user@test.com", "Hello, World! (2026)", now)
    assert "," not in name
    assert "!" not in name
    assert "(" not in name
    assert ")" not in name


def test_make_pdf_filename_truncates_long_subject():
    now = datetime(2026, 5, 24, 2, 0, 0, tzinfo=timezone.utc)
    long_subject = "A" * 200
    name = make_pdf_filename("user@test.com", long_subject, now)
    # subject slug should be capped at 60 chars
    parts = name[:-4].split("_", 2)  # strip .pdf, split date_sender_slug
    slug = parts[2]
    assert len(slug) <= 60
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_main.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement email_reader/main.py**

```python
# email_reader/main.py
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytz

from .config import load_app_config, load_db_credentials, AppConfig
from .db import (
    bootstrap_schema,
    connect,
    insert_message,
    load_parameters,
    message_exists,
)
from .gmail import (
    build_gmail_service,
    extract_body_html,
    fetch_message,
    get_header,
    list_inbox_messages,
    mark_as_read,
)
from .notifier import FailureRecord, evaluate_and_notify
from .pdf import PdfRenderer, RenderError
from .run_logger import RunLogger
from .url_detector import detect_content

log = logging.getLogger(__name__)
_SGT = pytz.timezone("Asia/Singapore")


def _parse_hhmm(hhmm: str) -> tuple:
    h, m = hhmm.split(":")
    return int(h), int(m)


def is_in_operating_window(config: AppConfig, now_utc: datetime) -> bool:
    sgt = now_utc.astimezone(_SGT)
    start_h, start_m = _parse_hhmm(config.operating_window_start)
    end_h, end_m = _parse_hhmm(config.operating_window_end)
    current = sgt.hour * 60 + sgt.minute
    return (start_h * 60 + start_m) <= current < (end_h * 60 + end_m)


def make_pdf_filename(sender: str, subject: str, now_utc: datetime) -> str:
    date_str = now_utc.strftime("%Y%m%d")
    local_part = sender.split("@")[0] if "@" in sender else sender
    local_part = re.sub(r"[^\w]", "_", local_part)[:20]
    slug = re.sub(r"[^\w]", "_", subject.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")[:60]
    return f"{date_str}_{local_part}_{slug}.pdf"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if len(sys.argv) != 2:
        print("Usage: email-reader <path-to-credentials-file>", file=sys.stderr)
        sys.exit(1)

    creds = load_db_credentials(sys.argv[1])
    conn = connect(creds)
    bootstrap_schema(conn)
    params = load_parameters(conn)
    config = load_app_config(params)

    now_utc = datetime.now(timezone.utc)

    if not is_in_operating_window(config, now_utc):
        log.info("Outside operating window (%s–%s SGT) — exiting.",
                 config.operating_window_start, config.operating_window_end)
        conn.close()
        sys.exit(0)

    run_logger = RunLogger(conn)
    renderer = PdfRenderer(paywall_text_threshold=config.paywall_text_threshold)
    failures: list = []

    try:
        service = build_gmail_service(
            config.gmail_client_id,
            config.gmail_client_secret,
            config.gmail_refresh_token,
        )
        renderer.open()
        messages = list_inbox_messages(service, config.mark_read)
        log.info("Found %d messages in inbox", len(messages))

        for msg_ref in messages:
            msg_id = msg_ref["id"]

            if message_exists(conn, msg_id):
                run_logger.log_message(msg_id, "", "", "skipped")
                log.debug("Skipping already-processed message %s", msg_id)
                continue

            message = fetch_message(service, msg_id)
            sender = get_header(message, "From")
            subject = get_header(message, "Subject")
            html_body, cid_map = extract_body_html(message)

            result = detect_content(
                html_body,
                cid_map,
                config.url_detection_threshold,
                config.url_blocklist,
            )

            try:
                if result.source == "url":
                    pdf_bytes = renderer.render_url(result.url)
                    disposition = "url_rendered"
                else:
                    pdf_bytes = renderer.render_html(result.html)
                    disposition = "body_rendered"

                filename = make_pdf_filename(sender, subject, now_utc)
                pdf_path = str(Path(config.pdf_output_dir) / filename)
                Path(pdf_path).write_bytes(pdf_bytes)

                insert_message(conn, msg_id, sender, subject,
                               result.url, pdf_path, pdf_bytes)

                if config.mark_read:
                    mark_as_read(service, msg_id)

                run_logger.log_message(msg_id, sender, subject, disposition)
                log.info("Processed %s → %s", msg_id, disposition)

            except RenderError as exc:
                failures.append(
                    FailureRecord(
                        gmail_message_id=msg_id,
                        sender=sender,
                        subject=subject,
                        url=result.url,
                        reason=exc.reason,
                    )
                )
                run_logger.log_message(msg_id, sender, subject, "failed")
                log.warning("Failed to render %s: %s", msg_id, exc.reason)

        evaluate_and_notify(conn, service, config, failures, now_utc)

    finally:
        renderer.close()
        run_logger.finish()
        conn.close()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_main.py -v
```

Expected: 7 tests PASSED.

- [ ] **Step 5: Run the full test suite with coverage**

```bash
pytest --cov=email_reader --cov-report=term-missing tests/
```

Expected: all tests pass; coverage ≥ 80%.

- [ ] **Step 6: Commit**

```bash
git add email_reader/main.py tests/test_main.py
git commit -m "feat: add main orchestration with operating window check and full pipeline"
```

---

## Task 10: Systemd Units and Deployment Script

**Files:**
- Create: `systemd/email-reader.service`
- Create: `systemd/email-reader.timer`
- Create: `setup.sh`

- [ ] **Step 1: Create systemd/email-reader.service**

```ini
[Unit]
Description=Gmail-to-PDF Email Reader
After=network.target postgresql.service

[Service]
Type=oneshot
User=email-reader
ExecStart=/opt/email-reader/venv/bin/email-reader /etc/email-reader/credentials.txt
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal
```

- [ ] **Step 2: Create systemd/email-reader.timer**

```ini
[Unit]
Description=Gmail-to-PDF Email Reader Timer

[Timer]
OnBootSec=2min
OnUnitActiveSec=__POLL_INTERVAL__min

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Create setup.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

CREDENTIALS_FILE="${1:?Usage: setup.sh <path-to-credentials-file>}"
INSTALL_DIR="/opt/email-reader"
VENV="$INSTALL_DIR/venv"
SYSTEMD_DIR="/etc/systemd/system"
CONF_DIR="/etc/email-reader"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Reading poll interval from database..."
POLL_INTERVAL=$(python3 - "$CREDENTIALS_FILE" <<'PYEOF'
import sys
import psycopg2
lines = open(sys.argv[1]).read().strip().splitlines()
host, port, user, password = [l.strip() for l in lines]
conn = psycopg2.connect(host=host, port=int(port), user=user,
                        password=password, dbname="mailpoller")
cur = conn.cursor()
cur.execute("SELECT value FROM parameters WHERE key = 'poll_interval_minutes'")
row = cur.fetchone()
print(row[0] if row else "30")
conn.close()
PYEOF
)

echo "Poll interval: ${POLL_INTERVAL} minutes"

# Create system user if it does not exist
id -u email-reader &>/dev/null || \
    useradd --system --no-create-home --shell /bin/false email-reader

# Create directories
mkdir -p "$INSTALL_DIR" "$CONF_DIR"

# Create venv and install package
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install -e "$REPO_DIR" --quiet
"$VENV/bin/playwright" install chromium

# Install credentials file (owner email-reader, mode 0600)
install -o email-reader -g email-reader -m 0600 \
    "$CREDENTIALS_FILE" "$CONF_DIR/credentials.txt"

# Install systemd units (substituting poll interval into timer)
sed "s/__POLL_INTERVAL__/${POLL_INTERVAL}/" \
    "$REPO_DIR/systemd/email-reader.timer" > "$SYSTEMD_DIR/email-reader.timer"
cp "$REPO_DIR/systemd/email-reader.service" "$SYSTEMD_DIR/email-reader.service"

# Enable and start
systemctl daemon-reload
systemctl enable email-reader.timer
systemctl start email-reader.timer

echo ""
echo "Installation complete."
systemctl status email-reader.timer --no-pager
```

- [ ] **Step 4: Make setup.sh executable**

```bash
chmod +x setup.sh
```

- [ ] **Step 5: Verify the console script entry point resolves**

```bash
source .venv/bin/activate
email-reader --help 2>&1 || true
```

Expected: prints `Usage: email-reader <path-to-credentials-file>` (exits with code 1, which is correct — no credentials file provided).

- [ ] **Step 6: Commit**

```bash
git add systemd/email-reader.service systemd/email-reader.timer setup.sh
git commit -m "chore: add systemd service/timer units and deployment setup.sh"
```

---

## Final Verification

- [ ] **Run the full test suite**

```bash
pytest --cov=email_reader --cov-report=term-missing -v tests/
```

Expected: all tests pass, coverage ≥ 80%.

- [ ] **Verify package installs cleanly into a fresh venv**

```bash
python3 -m venv /tmp/test-install-venv
/tmp/test-install-venv/bin/pip install -e . --quiet
/tmp/test-install-venv/bin/email-reader 2>&1 || true
```

Expected: `Usage: email-reader <path-to-credentials-file>`

- [ ] **Final commit**

```bash
git add -A
git status  # verify nothing sensitive is staged (.env files, credentials)
git commit -m "chore: final integration verification"
```
