# Gmail-to-PDF Pipeline — Design Spec

**Date:** 2026-05-24  
**Status:** Approved

---

## Overview

A Python program that connects to a Gmail account (`bumbojavalovernet@gmail.com`), reads inbox messages containing geopolitical or IT content, converts each message's content (from the email body or a linked URL) into a PDF file, stores the PDF on disk and in PostgreSQL, and runs as a Linux systemd service on a configurable interval.

---

## Package Structure

```
email_reader/
├── __init__.py
├── main.py          # Entry point: parses argv, orchestrates the pipeline
├── config.py        # Loads DB credentials file + fetches params table into a dataclass
├── db.py            # PostgreSQL connection, all SQL queries, schema bootstrap
├── gmail.py         # Gmail OAuth2 token refresh, list/fetch messages
├── url_detector.py  # Heuristic: body length vs threshold, anchor-text scoring, blocklist
├── pdf.py           # Playwright + Chromium rendering (URL or HTML body → PDF bytes)
├── notifier.py      # Builds and sends the error-summary email via Gmail API
└── run_logger.py    # Creates run record, appends message records, closes run record

systemd/
├── email-reader.service
└── email-reader.timer

pyproject.toml
requirements.txt
setup.sh             # Deployment script: venv, deps, Playwright browser, systemd units
```

---

## Entry Point Flow (`main.py`)

1. Parse single CLI argument: absolute path to a 4-line DB credentials file
2. Connect to PostgreSQL; bootstrap schema if tables don't exist
3. Load all parameters from the `parameters` table
4. Open a Playwright Chromium browser instance (reused across all messages in the run)
5. Fetch unread Gmail messages for `bumbojavalovernet@gmail.com`
6. For each message:
   a. Check `messages.gmail_message_id` — skip if already present (`disposition = skipped`)
   b. Detect content source (URL or body)
   c. Render PDF via Playwright
   d. Write PDF to disk and insert row into `messages`
   e. Append row to `run_messages`
7. If any failures accumulated: send one summary email to `eliobonazzi@gmail.com`
8. Close Playwright browser
9. Update `runs` row with `finished_at`, `messages_processed`, `messages_errored`

---

## Database Schema

### `parameters`
| Column  | Type    | Notes                          |
|---------|---------|-------------------------------|
| `key`   | TEXT PK |                               |
| `value` | TEXT    | All values stored as text     |

**Required parameter keys:**

| Key | Description | Default |
|-----|-------------|---------|
| `gmail_client_id` | OAuth2 client ID | — |
| `gmail_client_secret` | OAuth2 client secret | — |
| `gmail_refresh_token` | OAuth2 refresh token | — |
| `gmail_user` | Gmail address to poll | `bumbojavalovernet@gmail.com` |
| `pdf_output_dir` | Absolute path for PDF files on disk | — |
| `mark_read` | Mark processed messages as read (`true`/`false`) | `false` |
| `url_detection_threshold` | Max visible-text chars to classify as URL message | `500` |
| `paywall_text_threshold` | Min rendered visible-text chars before flagging paywall | `200` |
| `url_blocklist` | Newline-separated URL substrings to never render | `commonsense-computing.com/efb.html` |
| `poll_interval_minutes` | Run interval (used by setup.sh to write systemd timer) | `30` |

---

### `messages`
| Column             | Type         | Notes                                      |
|--------------------|--------------|--------------------------------------------|
| `id`               | BIGSERIAL PK |                                            |
| `gmail_message_id` | TEXT UNIQUE  | Indexed; used for dedup                   |
| `created_at`       | TIMESTAMPTZ  | Time row was inserted                      |
| `sender`           | TEXT         |                                            |
| `subject`          | TEXT         |                                            |
| `content_url`      | TEXT         | NULL if content came from email body       |
| `pdf_path`         | TEXT         | Full path on disk                          |
| `pdf_data`         | BYTEA        | Full PDF content; no size cap              |

---

### `runs`
| Column               | Type         | Notes                                                                      |
|----------------------|--------------|----------------------------------------------------------------------------|
| `id`                 | BIGSERIAL PK |                                                                            |
| `started_at`         | TIMESTAMPTZ  |                                                                            |
| `finished_at`        | TIMESTAMPTZ  | Updated at end of run                                                      |
| `messages_processed` | INT          | Count of non-skipped messages attempted (successful + failed; not skipped) |
| `messages_errored`   | INT          | Count of failed messages (subset of `messages_processed`)                  |

---

### `run_messages`
| Column             | Type         | Notes                                                          |
|--------------------|--------------|----------------------------------------------------------------|
| `id`               | BIGSERIAL PK |                                                               |
| `run_id`           | BIGINT FK    | References `runs.id`                                          |
| `processed_at`     | TIMESTAMPTZ  |                                                               |
| `gmail_message_id` | TEXT         |                                                               |
| `sender`           | TEXT         |                                                               |
| `subject`          | TEXT         |                                                               |
| `disposition`      | TEXT         | `skipped` / `body_rendered` / `url_rendered` / `failed`      |

---

## Gmail Integration (`gmail.py`)

- Uses OAuth2 refresh token flow via `google-auth` library — no interactive login at runtime.
- On startup: exchange `gmail_client_id` + `gmail_client_secret` + `gmail_refresh_token` for a short-lived access token. Token is auto-refreshed when expired.
- Fetches messages via Gmail REST API (`google-api-python-client`): label `INBOX`, label `UNREAD` (unless `mark_read=false`, in which case all INBOX messages are fetched for debugging).
- After successful processing of a message: if `mark_read=true`, remove the `UNREAD` label via the API.

---

## Content Detection (`url_detector.py`)

1. Strip email body HTML to visible text; count characters.
2. If character count < `url_detection_threshold`: classify as **URL message**.
3. For URL messages:
   - Parse all `<a href>` tags from the HTML body.
   - Filter out any URL whose href contains a substring from `url_blocklist`.
   - Score remaining links by anchor text length (longer = higher score).
   - Select the highest-scoring link as `content_url`.
   - If no qualifying URL remains after filtering: fall back to body rendering.
4. For body messages:
   - Extract full HTML body.
   - Inline `cid:` embedded images as base64 `<img src="data:...">` tags.
   - Wrap in a minimal standalone HTML page.
   - Pass to Playwright for rendering.

---

## PDF Rendering (`pdf.py`)

- One Playwright Chromium browser instance is launched per program run (not per message).
- **URL rendering:** `page.goto(url, wait_until="networkidle", timeout=30000)` — waits for all JS and images to settle.
- **Body rendering:** `page.set_content(html)` + `page.wait_for_load_state("networkidle")`.
- PDF printed with `page.pdf(format="A4", print_background=True)`.
- Returns PDF as `bytes`. Empty bytes → failure.

**Failure conditions** (message marked `failed`, added to error batch):
- `page.goto()` raises `TimeoutError` or network exception
- HTTP response status 4xx or 5xx (intercepted via Playwright response listener)
- Rendered visible text < `paywall_text_threshold` characters (paywall/login-wall heuristic)
- Rendered page contains `<input type="password">` (login form detection)
- Returned PDF bytes are empty
- Any unhandled Playwright exception

---

## PDF File Naming

Files are written to `pdf_output_dir` with the pattern:

```
{YYYYMMDD}_{sender_localpart}_{subject_slug}.pdf
```

Where `subject_slug` is the subject line lowercased, non-alphanumeric characters replaced with underscores, truncated to 60 characters.

Example: `20260524_newsletter_the_future_of_nato_supply_chains.pdf`

---

## Error Notification (`notifier.py`)

- Accumulates all failed messages during a run.
- At end of run, if any failures exist: sends **one email** from `bumbojavalovernet@gmail.com` to `eliobonazzi@gmail.com` via the Gmail API.
- Email body lists for each failure: Gmail message ID, sender, subject line, URL (if applicable), failure reason.
- No email is sent if there are zero failures.

---

## Systemd Packaging

**Credentials file** (4 lines, path passed as sole CLI argument):
```
hostname
port
mailpoller
password
```

**`email-reader.service`:**
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

**`email-reader.timer`:**
```ini
[Unit]
Description=Gmail-to-PDF Email Reader Timer

[Timer]
OnBootSec=2min
OnUnitActiveSec=__POLL_INTERVAL__min

[Install]
WantedBy=timers.target
```

`setup.sh` accepts the credentials file path as its sole argument, connects to the database to read `poll_interval_minutes`, and substitutes it into the timer unit at install time. To change the interval: update the DB row, re-run `setup.sh /path/to/credentials.txt`.

---

## Key Dependencies

| Library | Purpose |
|---------|---------|
| `playwright` | Headless Chromium rendering |
| `google-api-python-client` | Gmail REST API |
| `google-auth` | OAuth2 token refresh |
| `psycopg2-binary` | PostgreSQL driver |
| `beautifulsoup4` | HTML parsing for URL/body detection |
| `lxml` | HTML parser backend for BeautifulSoup |

---

## Constraints & Decisions

- **No async:** Sequential processing per run; Playwright is used synchronously. Sufficient for a personal inbox.
- **Chromium reuse:** Browser launched once per run to avoid per-message startup overhead.
- **PDF in BYTEA:** No size cap; all PDFs stored in full regardless of size.
- **Dedup by Gmail message ID:** Unique index on `messages.gmail_message_id` ensures idempotency.
- **One error email per run:** Failures batched into a single notification, not one email per failed message.
- **Blocklist in DB:** `url_blocklist` parameter contains newline-separated substrings; `commonsense-computing.com/efb.html` is the initial entry.
- **Poll interval in systemd:** `poll_interval_minutes` is read from DB at deploy time by `setup.sh` and written into the timer unit; not read dynamically at runtime.
