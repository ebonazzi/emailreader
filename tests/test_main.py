import psycopg2
import pytest
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from tests.conftest import make_config
from email_reader.main import is_in_operating_window, make_pdf_filename, main
from email_reader.pdf import RenderError


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
    name = make_pdf_filename("newsletter@example.com", "The Future of NATO", now, "abc12345")
    assert name.startswith("20260524_newsletter_")
    assert name.endswith(".pdf")
    assert "nato" in name
    assert "future" in name
    assert "abc12345" in name


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


def test_make_pdf_filename_empty_subject_uses_fallback():
    now = datetime(2026, 5, 24, 2, 0, 0, tzinfo=timezone.utc)
    name = make_pdf_filename("user@test.com", "", now, "zz99")
    assert "no_subject" in name
    assert "zz99" in name
    assert name.endswith(".pdf")


# ---------------------------------------------------------------------------
# Helpers for main() integration tests
# ---------------------------------------------------------------------------

def _make_message_ref(msg_id: str) -> dict:
    return {"id": msg_id}


def _make_gmail_message(sender: str, subject: str, html: str = "<p>body</p>") -> dict:
    return {
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
            ],
            "mimeType": "text/html",
            "body": {"data": ""},
            "parts": [],
        }
    }


@pytest.fixture
def mock_main_deps(tmp_path):
    """Patch all external dependencies of main() and return a helper dict."""
    creds_file = tmp_path / "creds.txt"
    creds_file.write_text("host=localhost\nport=5432\nusername=user\npassword=pass\n")
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()

    with (
        patch("email_reader.main.load_db_credentials") as mock_load_creds,
        patch("email_reader.main.connect") as mock_connect,
        patch("email_reader.main.bootstrap_schema"),
        patch("email_reader.main.load_parameters") as mock_load_params,
        patch("email_reader.main.load_app_config") as mock_load_config,
        patch("email_reader.main.build_gmail_service") as mock_build_service,
        patch("email_reader.main.PdfRenderer") as mock_renderer_cls,
        patch("email_reader.main.list_inbox_messages") as mock_list,
        patch("email_reader.main.message_exists") as mock_exists,
        patch("email_reader.main.fetch_message") as mock_fetch,
        patch("email_reader.main.get_header") as mock_get_header,
        patch("email_reader.main.extract_body_html") as mock_extract,
        patch("email_reader.main.detect_content") as mock_detect,
        patch("email_reader.main.insert_message") as mock_insert,
        patch("email_reader.main.mark_as_read"),
        patch("email_reader.main.RunLogger") as mock_run_logger_cls,
        patch("email_reader.main.evaluate_and_notify"),
        patch("email_reader.main.is_in_operating_window", return_value=True),
        patch("email_reader.main.Path.mkdir"),
        patch("email_reader.main.Path.write_bytes"),
    ):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        cfg = make_config(pdf_output_dir=str(pdf_dir))
        mock_load_config.return_value = cfg
        mock_load_params.return_value = {}
        mock_load_creds.return_value = MagicMock()

        mock_renderer = MagicMock()
        mock_renderer_cls.return_value.__enter__ = MagicMock(return_value=mock_renderer)
        mock_renderer_cls.return_value.__exit__ = MagicMock(return_value=False)

        mock_run_logger = MagicMock()
        mock_run_logger_cls.return_value = mock_run_logger

        yield {
            "conn": mock_conn,
            "config": cfg,
            "mock_load_config": mock_load_config,
            "mock_list": mock_list,
            "mock_exists": mock_exists,
            "mock_fetch": mock_fetch,
            "mock_get_header": mock_get_header,
            "mock_extract": mock_extract,
            "mock_detect": mock_detect,
            "mock_insert": mock_insert,
            "mock_renderer": mock_renderer,
            "mock_run_logger": mock_run_logger,
            "creds_file": creds_file,
        }


def _run_main(creds_file: Path) -> None:
    with patch.object(sys, "argv", ["email-reader", str(creds_file)]):
        main()


def test_main_skips_subject_blocklist_match(mock_main_deps):
    """Messages whose subject contains a blocklisted entry are skipped."""
    deps = mock_main_deps
    cfg = make_config(subject_line_blocklist=("unsubscribe",))
    deps["mock_load_config"].return_value = cfg

    deps["mock_list"].return_value = [_make_message_ref("msg1")]
    deps["mock_exists"].return_value = False
    deps["mock_get_header"].side_effect = lambda msg, name: (
        "sender@example.com" if name == "From" else "Please Unsubscribe Now"
    )

    _run_main(deps["creds_file"])

    deps["mock_run_logger"].log_message.assert_called_once_with(
        "msg1", "sender@example.com", "Please Unsubscribe Now", "skipped"
    )
    deps["mock_insert"].assert_not_called()


def test_main_subject_blocklist_case_insensitive(mock_main_deps):
    """Subject blocklist matching is case-insensitive."""
    deps = mock_main_deps
    cfg = make_config(subject_line_blocklist=("NEWSLETTER",))
    deps["mock_load_config"].return_value = cfg

    deps["mock_list"].return_value = [_make_message_ref("msg2")]
    deps["mock_exists"].return_value = False
    deps["mock_get_header"].side_effect = lambda msg, name: (
        "a@b.com" if name == "From" else "Weekly Newsletter Update"
    )

    _run_main(deps["creds_file"])

    deps["mock_run_logger"].log_message.assert_called_once_with(
        "msg2", "a@b.com", "Weekly Newsletter Update", "skipped"
    )


def test_main_no_subject_blocklist_proceeds_normally(mock_main_deps, tmp_path):
    """With no subject blocklist, message proceeds to PDF rendering."""
    deps = mock_main_deps
    deps["mock_list"].return_value = [_make_message_ref("msg3")]
    deps["mock_exists"].return_value = False
    deps["mock_get_header"].side_effect = lambda msg, name: (
        "a@b.com" if name == "From" else "Normal Subject"
    )
    deps["mock_extract"].return_value = ("<p>html</p>", {})
    result = MagicMock()
    result.source = "html"
    result.html = "<p>html</p>"
    result.url = None
    deps["mock_detect"].return_value = result
    deps["mock_renderer"].render_html.return_value = b"%PDF-1.4"

    _run_main(deps["creds_file"])

    deps["mock_insert"].assert_called_once()
    call_args = deps["mock_insert"].call_args[0]
    assert call_args[0] == deps["conn"]
    assert call_args[1] == "msg3"


def test_main_render_error_inserts_exception_record(mock_main_deps):
    """When RenderError is raised, insert_message is called with the exception text."""
    deps = mock_main_deps
    deps["mock_list"].return_value = [_make_message_ref("msg4")]
    deps["mock_exists"].return_value = False
    deps["mock_get_header"].side_effect = lambda msg, name: (
        "a@b.com" if name == "From" else "Some Subject"
    )
    deps["mock_extract"].return_value = ("<p>html</p>", {})
    result = MagicMock()
    result.source = "url"
    result.url = "https://example.com"
    deps["mock_detect"].return_value = result
    deps["mock_renderer"].render_url.side_effect = RenderError("render failed")

    _run_main(deps["creds_file"])

    deps["mock_insert"].assert_called_once()
    kw = deps["mock_insert"].call_args[1]
    assert kw.get("exception") == "render failed"


def test_main_outer_exception_inserts_exception_record(mock_main_deps):
    """When an outer Exception is raised during processing, insert_message records it."""
    deps = mock_main_deps
    deps["mock_list"].return_value = [_make_message_ref("msg5")]
    deps["mock_exists"].return_value = False
    deps["mock_fetch"].side_effect = RuntimeError("network error")

    _run_main(deps["creds_file"])

    deps["mock_insert"].assert_called_once()
    kw = deps["mock_insert"].call_args[1]
    assert kw.get("exception") == "network error"


def test_main_already_processed_message_is_skipped(mock_main_deps):
    """Messages already in the DB are skipped without calling insert_message."""
    deps = mock_main_deps
    deps["mock_list"].return_value = [_make_message_ref("msg6")]
    deps["mock_exists"].return_value = True

    _run_main(deps["creds_file"])

    deps["mock_insert"].assert_not_called()
    deps["mock_run_logger"].log_message.assert_called_once_with("msg6", "", "", "skipped")


def test_main_outer_exception_insert_failure_suppressed(mock_main_deps):
    """If insert_message itself fails during outer exception handling, error is suppressed."""
    deps = mock_main_deps
    deps["mock_list"].return_value = [_make_message_ref("msg7")]
    deps["mock_exists"].return_value = False
    deps["mock_fetch"].side_effect = RuntimeError("network error")
    deps["mock_insert"].side_effect = psycopg2.OperationalError("db down")

    # Should not raise despite db insert failure
    _run_main(deps["creds_file"])
