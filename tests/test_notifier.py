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
