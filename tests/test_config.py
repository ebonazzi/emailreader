# tests/test_config.py
import pytest
from pathlib import Path
from email_reader.config import load_db_credentials, load_app_config, DbCredentials, AppConfig


def test_load_db_credentials_parses_key_value(tmp_path):
    f = tmp_path / "creds.txt"
    f.write_text("host=myhost\nport=5432\nusername=mailpoller\npassword=secret\n")
    creds = load_db_credentials(str(f))
    assert creds.host == "myhost"
    assert creds.port == 5432
    assert creds.user == "mailpoller"
    assert creds.password == "secret"


def test_load_db_credentials_ignores_blank_lines_and_comments(tmp_path):
    f = tmp_path / "creds.txt"
    f.write_text("# DB credentials\nhost=myhost\n\nport=5432\nusername=mailpoller\npassword=secret\n")
    creds = load_db_credentials(str(f))
    assert creds.host == "myhost"
    assert creds.port == 5432


def test_load_db_credentials_rejects_invalid_line(tmp_path):
    f = tmp_path / "creds.txt"
    f.write_text("host=myhost\nport=5432\nusername=mailpoller\nbadline\n")
    with pytest.raises(ValueError, match="key=value"):
        load_db_credentials(str(f))


def test_load_db_credentials_rejects_missing_key(tmp_path):
    f = tmp_path / "creds.txt"
    f.write_text("host=myhost\nport=5432\nusername=mailpoller\n")
    with pytest.raises(ValueError, match="Missing required credential key"):
        load_db_credentials(str(f))


def test_load_app_config_uses_defaults():
    params = {
        "gmail_client_id": "cid",
        "gmail_client_secret": "csecret",
        "gmail_refresh_token": "rtoken",
        "pdf_output_dir": "/tmp/pdfs",
    }
    config = load_app_config(params)
    assert config.url_detection_threshold == 500
    assert config.paywall_text_threshold == 200
    assert config.mark_read is False
    assert config.email_failure_send == "daily"
    assert config.operating_window_start == "07:00"
    assert config.operating_window_end == "20:00"
    assert config.daily_digest_time == "19:30"
    assert "commonsense-computing.com/efb.html" in config.url_blocklist
    assert config.gmail_user == "bumbojavalovernet@gmail.com"
    assert config.poll_interval_minutes == 30


def test_load_app_config_mark_read_true():
    params = {
        "gmail_client_id": "cid",
        "gmail_client_secret": "csecret",
        "gmail_refresh_token": "rtoken",
        "pdf_output_dir": "/tmp/pdfs",
        "mark_read": "true",
    }
    config = load_app_config(params)
    assert config.mark_read is True


def test_load_app_config_pipe_delimited_url_blocklist():
    params = {
        "gmail_client_id": "cid",
        "gmail_client_secret": "csecret",
        "gmail_refresh_token": "rtoken",
        "pdf_output_dir": "/tmp/pdfs",
        "url_blocklist": "example.com|other.com",
    }
    config = load_app_config(params)
    assert "example.com" in config.url_blocklist
    assert "other.com" in config.url_blocklist
    assert len(config.url_blocklist) == 2


def test_load_app_config_subject_line_blocklist_parsed():
    params = {
        "gmail_client_id": "cid",
        "gmail_client_secret": "csecret",
        "gmail_refresh_token": "rtoken",
        "pdf_output_dir": "/tmp/pdfs",
        "subject_line_blocklist": "unsubscribe|newsletter",
    }
    config = load_app_config(params)
    assert "unsubscribe" in config.subject_line_blocklist
    assert "newsletter" in config.subject_line_blocklist
    assert len(config.subject_line_blocklist) == 2


def test_load_app_config_subject_line_blocklist_defaults_empty():
    params = {
        "gmail_client_id": "cid",
        "gmail_client_secret": "csecret",
        "gmail_refresh_token": "rtoken",
        "pdf_output_dir": "/tmp/pdfs",
    }
    config = load_app_config(params)
    assert config.subject_line_blocklist == ()


def test_load_app_config_missing_required_key_raises():
    with pytest.raises(KeyError):
        load_app_config({})


def test_load_app_config_each_required_key_raises_individually():
    base = {
        "gmail_client_id": "cid",
        "gmail_client_secret": "csecret",
        "gmail_refresh_token": "rtoken",
        "pdf_output_dir": "/tmp/pdfs",
    }
    for key in ("gmail_client_id", "gmail_client_secret", "gmail_refresh_token", "pdf_output_dir"):
        params = {k: v for k, v in base.items() if k != key}
        with pytest.raises(KeyError):
            load_app_config(params)
