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


def _parse_hhmm(hhmm: str) -> tuple[int, int]:
    try:
        h, m = hhmm.split(":")
        return int(h), int(m)
    except ValueError as exc:
        raise ValueError(f"Invalid HH:MM time {hhmm!r} in config: {exc}") from exc


def is_in_operating_window(config: AppConfig, now_utc: datetime) -> bool:
    sgt = now_utc.astimezone(_SGT)
    start_h, start_m = _parse_hhmm(config.operating_window_start)
    end_h, end_m = _parse_hhmm(config.operating_window_end)
    current = sgt.hour * 60 + sgt.minute
    return (start_h * 60 + start_m) <= current < (end_h * 60 + end_m)


def make_pdf_filename(sender: str, subject: str, now_utc: datetime, msg_id: str = "") -> str:
    sgt = now_utc.astimezone(_SGT)
    date_str = sgt.strftime("%Y%m%d")
    local_part = sender.split("@")[0] if "@" in sender else sender
    local_part = re.sub(r"[^\w]", "_", local_part)[:20]
    slug = re.sub(r"[^\w]", "_", subject.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")[:60]
    if not slug:
        slug = "no_subject"
    suffix = f"_{msg_id[:8]}" if msg_id else ""
    return f"{date_str}_{local_part}_{slug}{suffix}.pdf"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    print("DEBUG: main() started", flush=True)  # ADD THIS
    print(f"DEBUG: sys.argv={sys.argv}", flush=True)  # ADD THIS
    if len(sys.argv) != 2:
        print("Usage: email-reader <path-to-credentials-file>", file=sys.stderr)
        sys.exit(1)
    print("DEBUG: loading credentials", flush=True)  # ADD THIS
    creds = load_db_credentials(sys.argv[1])
    print(f"DEBUG: creds loaded", flush=True)  # ADD THIS
    conn = connect(creds)
    print("DEBUG: connected to DB", flush=True)  # ADD THIS
    bootstrap_schema(conn)
    params = load_parameters(conn)
    config = load_app_config(params)
    Path(config.pdf_output_dir).mkdir(parents=True, exist_ok=True)

    now_utc = datetime.now(timezone.utc)

    if not is_in_operating_window(config, now_utc):
        log.info(
            "Outside operating window (%s–%s SGT) — exiting.",
            config.operating_window_start,
            config.operating_window_end,
        )
        conn.close()
        sys.exit(0)

    run_logger = RunLogger(conn)
    failures: list[FailureRecord] = []

    try:
        service = build_gmail_service(
            config.gmail_client_id,
            config.gmail_client_secret,
            config.gmail_refresh_token,
        )
        with PdfRenderer(paywall_text_threshold=config.paywall_text_threshold) as renderer:
            messages = list_inbox_messages(service, config.mark_read)
            log.info("Found %d messages in inbox", len(messages))

            for msg_ref in messages:
                msg_id = msg_ref["id"]
                sender: str = "unknown"
                subject: str = ""
                result = None
                message_inserted: bool = False

                if message_exists(conn, msg_id):
                    run_logger.log_message(msg_id, "", "", "skipped")
                    log.debug("Skipping already-processed message %s", msg_id)
                    continue

                try:
                    message = fetch_message(service, msg_id)
                    sender = get_header(message, "From")
                    subject = get_header(message, "Subject")

                    if any(entry.lower() in subject.lower() for entry in config.subject_line_blocklist):
                        run_logger.log_message(msg_id, sender, subject, "skipped")
                        log.info("Skipping %s: subject matches blocklist (%r)", msg_id, subject)
                        continue

                    html_body, cid_map = extract_body_html(message)

                    result = detect_content(
                        html_body,
                        cid_map,
                        config.url_detection_threshold,
                        config.url_blocklist,
                    )

                    try:
                        if result.source == "url":
                            assert result.url is not None, f"detect_content returned url source with None url for {msg_id}"
                            pdf_bytes = renderer.render_url(result.url)
                            disposition = "url_rendered"
                        else:
                            pdf_bytes = renderer.render_html(result.html)
                            disposition = "body_rendered"

                        filename = make_pdf_filename(sender, subject, now_utc, msg_id)
                        pdf_path = str(Path(config.pdf_output_dir) / filename)
                        Path(pdf_path).write_bytes(pdf_bytes)

                        insert_message(conn, msg_id, sender, subject,
                                       result.url, pdf_path, pdf_bytes)
                        message_inserted = True

                        if config.mark_read:
                            mark_as_read(service, msg_id)

                        run_logger.log_message(msg_id, sender, subject, disposition)
                        log.info("Processed %s → %s", msg_id, disposition)

                    except RenderError as exc:
                        _url = result.url if result is not None else None
                        if not message_inserted:
                            insert_message(conn, msg_id, sender, subject, _url, None, None, exception=exc.reason)
                            message_inserted = True
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

                except Exception as exc:
                    _url = result.url if result is not None else None
                    if not message_inserted:
                        try:
                            insert_message(conn, msg_id, sender, subject, _url, None, None, exception=str(exc))
                        except Exception:
                            pass  # don't let insert failure mask the original error
                    failures.append(
                        FailureRecord(
                            gmail_message_id=msg_id,
                            sender=sender,
                            subject=subject,
                            url=_url,
                            reason=str(exc),
                        )
                    )
                    run_logger.log_message(msg_id, sender, subject, "failed")
                    log.warning("Unexpected error processing %s: %s", msg_id, exc, exc_info=True)

            evaluate_and_notify(conn, service, config, failures, now_utc)

    finally:
        run_logger.finish()
        conn.close()

if __name__ == "__main__":
    main()