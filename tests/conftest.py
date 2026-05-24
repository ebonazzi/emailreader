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
