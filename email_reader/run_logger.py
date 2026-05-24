# email_reader/run_logger.py
from __future__ import annotations

import logging

from .db import close_run, insert_run, insert_run_message

log = logging.getLogger(__name__)


class RunLogger:
    def __init__(self, conn: object) -> None:
        self._conn = conn
        self._run_id: int = insert_run(conn)
        self._processed: int = 0
        self._errored: int = 0

    @property
    def run_id(self) -> int:
        return self._run_id

    def log_message(
        self,
        gmail_message_id: str,
        sender: str,
        subject: str,
        disposition: str,
    ) -> None:
        insert_run_message(
            self._conn, self._run_id, gmail_message_id, sender, subject, disposition
        )
        if disposition != "skipped":
            self._processed += 1
        if disposition == "failed":
            self._errored += 1

    def finish(self) -> None:
        close_run(self._conn, self._run_id, self._processed, self._errored)
        log.info(
            "Run %d complete: %d processed, %d errored",
            self._run_id, self._processed, self._errored,
        )
