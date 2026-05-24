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
4. **Check operating window:** if current Singapore time (UTC+8) is before `operating_window_start` or at/after `operating_window_end`, log "outside operating window" and exit cleanly (code 0). The systemd timer continues firing unconditionally; the program self-regulates.
5. Open a Playwright Chromium browser instance (reused across all messages in the run)
6. Fetch unread Gmail messages for `bumbojavalovernet@gmail.com`
7. For each message:
   a. Check `messages.gmail_message_id` — skip if already present (`disposition = skipped`)
   b. Detect content source (URL or body)
   c. Render PDF via Playwright
   d. Write PDF to disk and insert row into `messages`
   e. Append row to `run_messages`
8. Evaluate failure notification (see `notifier.py` section)
9. Close Playwright browser
10. Update `runs` row with `finished_at`, `messages_processed`, `messages_errored`

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
| `email_failure_send` | When to send failure digest: `hourly` or `daily` | `daily` |
| `operating_window_start` | Earliest SGT time to process (HH:MM, 24h) | `07:00` |
| `operating_window_end` | Latest SGT time to process (HH:MM, 24h) | `20:00` |
| `daily_digest_time` | SGT time to send daily failure digest (HH:MM, 24h); must be before `operating_window_end` | `19:30` |

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

### `notification_log`
| Column              | Type         | Notes                                                      |
|---------------------|--------------|------------------------------------------------------------|
| `id`                | BIGSERIAL PK |                                                            |
| `sent_at`           | TIMESTAMPTZ  | When the notification email was actually sent              |
| `notification_type` | TEXT         | `hourly_failures` or `daily_digest`                        |
| `failure_count`     | INT          | Number of failed messages covered by this notification     |

Used by the `daily` mode to determine whether today's digest (in Singapore time, UTC+8) has already been sent. The program queries for any `daily_digest` row whose `sent_at` date in SGT matches today before deciding to send.

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

Behaviour is controlled by the `email_failure_send` parameter:

Because the program only runs during the operating window (07:00–20:00 SGT by default), overnight email delivery is impossible by design — the program does not run overnight.

**`hourly` mode:**
- At end of each run (within the operating window), if any failures occurred: send one email immediately from `bumbojavalovernet@gmail.com` to `eliobonazzi@gmail.com` via the Gmail API.
- Email body lists for each failure: Gmail message ID, sender, subject line, URL (if applicable), failure reason.
- Records a `hourly_failures` row in `notification_log`.
- No email is sent if there are zero failures in that run.

**`daily` mode:**
- Failures accumulate silently in `run_messages` throughout the operating window.
- At end of each run, check whether a `daily_digest` notification has already been sent today (SGT date). If not, and if the current SGT time ≥ `daily_digest_time` (default 19:30): collect all `failed` dispositions from `run_messages` for today's SGT date, send one digest email.
- `daily_digest_time` defaults to 19:30 SGT — 30 minutes before the operating window closes — ensuring the digest is always sent within the active window.
- Records a `daily_digest` row in `notification_log` with `sent_at` = now and `failure_count` = number of failures included.
- If there are no failures for the day, no email is sent.

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
| `playwright`               | Headless Chromium rendering              |
| `google-api-python-client` | Gmail REST API                           |
| `google-auth`              | OAuth2 token refresh                     |
| `psycopg2-binary`          | PostgreSQL driver                        |
| `beautifulsoup4`           | HTML parsing for URL/body detection      |
| `lxml`                     | HTML parser backend for BeautifulSoup    |
| `pytz`                     | Singapore timezone (UTC+8) for daily digest window |

---

## Constraints & Decisions

- **No async:** Sequential processing per run; Playwright is used synchronously. Sufficient for a personal inbox.
- **Chromium reuse:** Browser launched once per run to avoid per-message startup overhead.
- **PDF in BYTEA:** No size cap; all PDFs stored in full regardless of size.
- **Dedup by Gmail message ID:** Unique index on `messages.gmail_message_id` ensures idempotency.
- **Operating window:** Program checks SGT time on startup and exits cleanly if outside `operating_window_start`–`operating_window_end` (default 07:00–20:00 SGT). The systemd timer fires unconditionally; the program self-regulates. This eliminates overnight email delivery entirely.
- **Failure notification mode:** `hourly` sends one email per run (if failures exist, within operating window only); `daily` accumulates failures and sends one digest at `daily_digest_time` (default 19:30 SGT, before window close). Default mode is `daily`.
- **Blocklist in DB:** `url_blocklist` parameter contains newline-separated substrings; `commonsense-computing.com/efb.html` is the initial entry.
- **Poll interval in systemd:** `poll_interval_minutes` is read from DB at deploy time by `setup.sh` and written into the timer unit; not read dynamically at runtime.
