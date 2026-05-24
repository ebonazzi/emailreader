# tests/test_gmail.py
import base64
import pytest
from unittest.mock import MagicMock, patch
from email_reader.gmail import (
    extract_body_html,
    get_header,
    mark_as_read,
    send_email,
    list_inbox_messages,
    fetch_message,
    build_gmail_service,
)


def _encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def make_message(html: str, extra_headers: list[dict] | None = None) -> dict:
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
    service.users().messages().modify().execute.assert_called_once()


def test_send_email_calls_gmail_api():
    service = MagicMock()
    send_email(service, "from@gmail.com", "to@gmail.com", "Subject", "Body text")
    service.users().messages().send.assert_called_once()
    call_kwargs = service.users().messages().send.call_args[1]
    assert call_kwargs["userId"] == "me"
    assert "raw" in call_kwargs["body"]
    service.users().messages().send().execute.assert_called_once()


def test_list_inbox_messages_mark_read_uses_unread_query():
    service = MagicMock()
    service.users().messages().list.return_value = MagicMock()
    service.users().messages().list.return_value.execute.return_value = {"messages": [{"id": "1"}]}
    service.users().messages().list_next.return_value = None
    result = list_inbox_messages(service, mark_read=True)
    call_kwargs = service.users().messages().list.call_args[1]
    assert "is:unread" in call_kwargs["q"]
    assert result == [{"id": "1"}]


def test_list_inbox_messages_no_mark_read_fetches_all_inbox():
    service = MagicMock()
    service.users().messages().list.return_value = MagicMock()
    service.users().messages().list.return_value.execute.return_value = {"messages": []}
    service.users().messages().list_next.return_value = None
    list_inbox_messages(service, mark_read=False)
    call_kwargs = service.users().messages().list.call_args[1]
    assert "is:unread" not in call_kwargs["q"]
    assert call_kwargs["q"] == "in:inbox"


def test_fetch_message_uses_full_format():
    service = MagicMock()
    service.users().messages().get.return_value.execute.return_value = {"id": "msg1"}
    result = fetch_message(service, "msg1")
    call_kwargs = service.users().messages().get.call_args[1]
    assert call_kwargs["format"] == "full"
    assert call_kwargs["id"] == "msg1"
    assert result == {"id": "msg1"}


def test_build_gmail_service_raises_on_empty_credentials():
    with pytest.raises(ValueError, match="non-empty"):
        build_gmail_service("", "secret", "token")
    with pytest.raises(ValueError, match="non-empty"):
        build_gmail_service("cid", "", "token")
    with pytest.raises(ValueError, match="non-empty"):
        build_gmail_service("cid", "secret", "")


def test_list_inbox_messages_paginates_multiple_pages():
    service = MagicMock()
    # First page returns one message and a nextPageToken
    first_request = MagicMock()
    first_result = {"messages": [{"id": "msg1"}], "nextPageToken": "tok"}
    first_request.execute.return_value = first_result
    # Second page returns one message and no nextPageToken
    second_request = MagicMock()
    second_result = {"messages": [{"id": "msg2"}]}
    second_request.execute.return_value = second_result
    # list_next returns second_request on first call, None on second
    service.users().messages().list.return_value = first_request
    service.users().messages().list_next.side_effect = [second_request, None]
    result = list_inbox_messages(service, mark_read=True)
    assert len(result) == 2
    assert result[0]["id"] == "msg1"
    assert result[1]["id"] == "msg2"
