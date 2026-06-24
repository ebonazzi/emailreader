# email_reader/gmail.py
import base64
import logging
from typing import Any
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

GmailService = Any  # google.api_core.discovery.Resource


def build_gmail_service(client_id: str, client_secret: str, refresh_token: str) -> GmailService:
    if not all([client_id, client_secret, refresh_token]):
        raise ValueError("client_id, client_secret, and refresh_token must all be non-empty")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://mail.google.com/"],
    )
    try:
        creds.refresh(Request())
    except RefreshError as exc:
        raise RuntimeError("Failed to refresh Gmail OAuth token") from exc
    return build("gmail", "v1", credentials=creds)


def list_inbox_messages(service: GmailService, mark_read: bool) -> list[dict]:
    query = "in:inbox is:unread" if mark_read else "in:inbox"
    messages: list[dict] = []
    request = service.users().messages().list(userId="me", q=query)
    while request is not None:
        result = request.execute()
        messages.extend(result.get("messages", []))
        request = service.users().messages().list_next(request, result)
    return messages


def fetch_message(service: GmailService, msg_id: str) -> dict:
    return (
        service.users()
        .messages()
        .get(userId="me", id=msg_id, format="full")
        .execute()
    )


def extract_body_html(message: dict) -> tuple[str, dict[str, bytes]]:
    """Return (html_body, cid_map) where cid_map maps Content-Id values to raw bytes."""
    payload = message.get("payload", {})
    html_body = ""
    cid_map: dict[str, bytes] = {}

    def _decode_str(data: str) -> str:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    def _decode_bytes(data: str) -> bytes:
        return base64.urlsafe_b64decode(data + "==")

    def walk(parts: list) -> None:
        nonlocal html_body
        for part in parts:
            mime = part.get("mimeType", "")
            body = part.get("body", {})
            data = body.get("data", "")
            sub_parts = part.get("parts", [])

            if mime == "text/html" and data and not html_body:
                html_body = _decode_str(data)
            elif mime.startswith("image/") and data:
                headers = {
                    h["name"].lower(): h["value"]
                    for h in part.get("headers", [])
                }
                cid = headers.get("content-id", "").strip("<>")
                if cid:
                    cid_map[cid] = _decode_bytes(data)

            if sub_parts:
                walk(sub_parts)

    if "parts" in payload:
        walk(payload["parts"])
    elif payload.get("mimeType") == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html_body = _decode_str(data)

    return html_body, cid_map


def get_header(message: dict, name: str) -> str:
    headers = message.get("payload", {}).get("headers", [])
    name_lower = name.lower()
    for h in headers:
        if h["name"].lower() == name_lower:
            return h["value"]
    return ""


def mark_as_read(service: GmailService, msg_id: str) -> None:
    service.users().messages().modify(
        userId="me",
        id=msg_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()


def send_email(service: GmailService, from_addr: str, to_addr: str, subject: str, body: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = to_addr
    msg["from"] = from_addr
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
