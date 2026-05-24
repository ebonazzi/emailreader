import pytest
from datetime import datetime, timezone
from tests.conftest import make_config
from email_reader.main import is_in_operating_window, make_pdf_filename


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
    name = make_pdf_filename("newsletter@example.com", "The Future of NATO", now)
    assert name.startswith("20260524_newsletter_")
    assert name.endswith(".pdf")
    assert "nato" in name
    assert "future" in name


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
    name = make_pdf_filename("user@test.com", "", now)
    assert "no_subject" in name
    assert name.endswith(".pdf")
