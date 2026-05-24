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
    # processed=2 (not skipped), errored=0
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


def test_run_logger_run_id_property(mock_conn):
    with patch("email_reader.run_logger.insert_run", return_value=42):
        logger = RunLogger(mock_conn)
    assert logger.run_id == 42


def test_run_logger_failed_counts_as_both_processed_and_errored(mock_conn):
    with patch("email_reader.run_logger.insert_run", return_value=3), \
         patch("email_reader.run_logger.insert_run_message"), \
         patch("email_reader.run_logger.close_run") as mock_close:
        logger = RunLogger(mock_conn)
        logger.log_message("id1", "a@b.com", "Subject", "failed")
        logger.finish()
    # A single "failed" message counts as processed=1 AND errored=1
    mock_close.assert_called_once_with(mock_conn, 3, 1, 1)
