# tests/test_gmail.py
import base64
import pytest
from unittest.mock import MagicMock, patch
from email_reader.gmail import (
    extract_body_html,
    get_header,
    mark_as_read,
    send_email,
)


def _encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def make_message(html: str, extra_headers: list = None) -> dict:
    headers = [
        {"name": "From", "value": "sender@example.com"},
        {"name": "Subject", "value": "Test Subject"},
    ]
    if extra_headers:
        headers.extend(extra_headers)
    return {
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": headers,
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _encoded(html)},
                    "headers": [],
                }
            ],
        }
    }


def test_extract_body_html_returns_html_content():
    msg = make_message("<p>Hello world</p>")
    html, cids = extract_body_html(msg)
    assert "<p>Hello world</p>" in html
    assert cids == {}


def test_extract_body_html_handles_flat_html_payload():
    encoded = _encoded("<p>Flat</p>")
    msg = {
        "payload": {
            "mimeType": "text/html",
            "headers": [],
            "body": {"data": encoded},
        }
    }
    html, cids = extract_body_html(msg)
    assert "<p>Flat</p>" in html


def test_extract_body_html_returns_empty_for_no_html_part():
    msg = {
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _encoded("plain text")},
                    "headers": [],
                }
            ],
        }
    }
    html, cids = extract_body_html(msg)
    assert html == ""


def test_extract_body_html_inlines_cid_attachment():
    img_data = base64.urlsafe_b64encode(b"\x89PNG").decode()
    msg = {
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [],
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _encoded("<img src='cid:img001'>")},
                    "headers": [],
                },
                {
                    "mimeType": "image/png",
                    "body": {"data": img_data},
                    "headers": [{"name": "Content-Id", "value": "<img001>"}],
                },
            ],
        }
    }
    html, cids = extract_body_html(msg)
    assert "img001" in cids
    assert len(cids["img001"]) > 0


def test_get_header_returns_value():
    msg = make_message("<p>hi</p>")
    assert get_header(msg, "From") == "sender@example.com"
    assert get_header(msg, "Subject") == "Test Subject"


def test_get_header_case_insensitive():
    msg = make_message("<p>hi</p>")
    assert get_header(msg, "from") == "sender@example.com"


def test_get_header_missing_returns_empty():
    msg = make_message("<p>hi</p>")
    assert get_header(msg, "X-Nonexistent") == ""


def test_mark_as_read_removes_unread_label():
    service = MagicMock()
    mark_as_read(service, "msg123")
    service.users().messages().modify.assert_called_once_with(
        userId="me",
        id="msg123",
        body={"removeLabelIds": ["UNREAD"]},
    )


def test_send_email_calls_gmail_api():
    service = MagicMock()
    send_email(service, "from@gmail.com", "to@gmail.com", "Subject", "Body text")
    service.users().messages().send.assert_called_once()
    call_kwargs = service.users().messages().send.call_args[1]
    assert call_kwargs["userId"] == "me"
    assert "raw" in call_kwargs["body"]
