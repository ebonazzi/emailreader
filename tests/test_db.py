# tests/test_db.py
import pytest
from unittest.mock import MagicMock
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


def test_bootstrap_schema_executes_six_statements(mock_conn):
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
