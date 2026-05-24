# email_reader/notifier.py
import logging
from dataclasses import dataclass
from datetime import datetime

import pytz

from .config import AppConfig
from .db import digest_sent_today, get_today_failed_messages, insert_notification_log
from .gmail import send_email

log = logging.getLogger(__name__)
_SGT = pytz.timezone("Asia/Singapore")

_RECIPIENT = "eliobonazzi@gmail.com"


@dataclass
class FailureRecord:
    gmail_message_id: str
    sender: str
    subject: str
    url: str | None
    reason: str


def _parse_hhmm(hhmm: str) -> tuple[int, int]:
    h, m = hhmm.split(":")
    return int(h), int(m)


def _build_hourly_body(failures: list[FailureRecord]) -> str:
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


def _build_daily_body(rows: list[dict]) -> str:
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
    conn: "psycopg2.extensions.connection",
    service,
    config: AppConfig,
    run_failures: list[FailureRecord],
    now_utc: datetime,
) -> None:
    sgt_now = now_utc.astimezone(_SGT)
    today_str = sgt_now.strftime("%Y-%m-%d")

    if config.email_failure_send == "hourly":
        if not run_failures:
            return
        body = _build_hourly_body(run_failures)
        send_email(
            service, config.gmail_user, _RECIPIENT,
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
            service, config.gmail_user, _RECIPIENT,
            f"Email Reader: daily failure digest ({len(failures)} failures)", body,
        )
        insert_notification_log(conn, "daily_digest", len(failures))
        log.info("Sent daily digest: %d failures", len(failures))
