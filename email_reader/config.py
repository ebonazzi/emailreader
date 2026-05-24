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
    url_blocklist: tuple[str, ...]
    subject_line_blocklist: tuple[str, ...]
    poll_interval_minutes: int
    email_failure_send: str
    operating_window_start: str
    operating_window_end: str
    daily_digest_time: str


def load_db_credentials(path: str | Path) -> DbCredentials:
    result: dict[str, str] = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid credentials line (expected key=value): {line!r}")
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    try:
        return DbCredentials(
            host=result["host"],
            port=int(result["port"]),
            user=result["username"],
            password=result["password"],
        )
    except KeyError as exc:
        raise ValueError(f"Missing required credential key: {exc}") from exc


def load_app_config(params: dict[str, str]) -> AppConfig:
    raw_blocklist = params.get("url_blocklist", "commonsense-computing.com/efb.html")
    blocklist = tuple(entry.strip() for entry in raw_blocklist.split("|") if entry.strip())
    raw_subject_blocklist = params.get("subject_line_blocklist", "")
    subject_blocklist = tuple(entry.strip() for entry in raw_subject_blocklist.split("|") if entry.strip())
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
        subject_line_blocklist=subject_blocklist,
        poll_interval_minutes=int(params.get("poll_interval_minutes", "30")),
        email_failure_send=params.get("email_failure_send", "daily"),
        operating_window_start=params.get("operating_window_start", "07:00"),
        operating_window_end=params.get("operating_window_end", "20:00"),
        daily_digest_time=params.get("daily_digest_time", "19:30"),
    )
