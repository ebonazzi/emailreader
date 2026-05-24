# email_reader/pdf.py
import logging

from playwright.sync_api import (
    Browser,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)

log = logging.getLogger(__name__)


class RenderError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PdfRenderer:
    def __init__(self, paywall_text_threshold: int) -> None:
        self._threshold = paywall_text_threshold
        self._pw: Playwright | None = None
        self._browser: Browser | None = None

    def open(self) -> None:
        self._pw = sync_playwright().start()
        # Use system Chrome — Playwright's bundled Chromium unsupported on Ubuntu 26.04
        self._browser = self._pw.chromium.launch(headless=True, channel="chrome")

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def __enter__(self) -> "PdfRenderer":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def render_url(self, url: str) -> bytes:
        if self._browser is None:
            raise RuntimeError("PdfRenderer is not open; call open() first")
        page = self._browser.new_page()
        try:
            bad_statuses: list[int] = []
            page.on(
                "response",
                lambda r: bad_statuses.append(r.status)
                if r.url == url and r.status >= 400
                else None,
            )
            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
            except PlaywrightTimeout:
                raise RenderError("timeout")
            except Exception as exc:
                raise RenderError(f"network error: {exc}") from exc

            if bad_statuses:
                raise RenderError(f"http {bad_statuses[0]}")

            try:
                self._check_page_content(page)
            except RenderError:
                raise
            except Exception as exc:
                raise RenderError(f"page content check failed: {exc}") from exc

            try:
                pdf = page.pdf(format="A4", print_background=True)
            except Exception as exc:
                raise RenderError(f"pdf generation failed: {exc}") from exc

            if not pdf:
                raise RenderError("empty pdf")
            return pdf
        finally:
            page.close()

    def render_html(self, html: str) -> bytes:
        if self._browser is None:
            raise RuntimeError("PdfRenderer is not open; call open() first")
        page = self._browser.new_page()
        try:
            page.set_content(html, wait_until="networkidle")
            self._check_page_content(page)
            pdf = page.pdf(format="A4", print_background=True)
            if not pdf:
                raise RenderError("empty pdf")
            return pdf
        except RenderError:
            raise
        except Exception as exc:
            raise RenderError(f"playwright error: {exc}")
        finally:
            page.close()

    def _check_page_content(self, page: Page) -> None:
        has_password = page.locator('input[type="password"]').count() > 0
        if has_password:
            raise RenderError("login form detected")
        text = page.evaluate("() => (document.body && document.body.innerText) || ''")  # guard null body
        if len(text.strip()) < self._threshold:
            raise RenderError(
                f"paywall suspected: only {len(text.strip())} chars visible"
            )
