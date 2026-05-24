# tests/test_pdf.py
import pytest
from unittest.mock import MagicMock, patch
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from email_reader.pdf import PdfRenderer, RenderError

LONG_HTML = (
    "<!DOCTYPE html><html><body><h1>Test Document</h1><p>"
    + ("This is content text for the document. " * 20)
    + "</p></body></html>"
)

SHORT_HTML = "<!DOCTYPE html><html><body><p>Login</p></body></html>"

LOGIN_HTML = (
    "<!DOCTYPE html><html><body>"
    '<form><input type="password" name="pw"><button>Sign in</button></form>'
    "</body></html>"
)


@pytest.fixture(scope="module")
def renderer():
    r = PdfRenderer(paywall_text_threshold=100)
    r.open()
    yield r
    r.close()


def test_render_html_returns_pdf_bytes(renderer):
    pdf = renderer.render_html(LONG_HTML)
    assert isinstance(pdf, bytes)
    assert len(pdf) > 0
    assert pdf[:4] == b"%PDF"


def test_render_html_raises_render_error_on_short_content(renderer):
    with pytest.raises(RenderError) as exc_info:
        renderer.render_html(SHORT_HTML)
    assert "paywall" in exc_info.value.reason


def test_render_html_raises_render_error_on_login_form(renderer):
    with pytest.raises(RenderError) as exc_info:
        renderer.render_html(LOGIN_HTML)
    assert "login form" in exc_info.value.reason


def test_render_error_has_reason_attribute():
    err = RenderError("timeout")
    assert err.reason == "timeout"
    assert "timeout" in str(err)


def test_render_url_timeout_raises_render_error():
    renderer = PdfRenderer(paywall_text_threshold=100)
    renderer._browser = MagicMock()
    page = MagicMock()
    renderer._browser.new_page.return_value = page
    page.goto.side_effect = PlaywrightTimeout("timed out")
    page.on.return_value = None
    with pytest.raises(RenderError) as exc_info:
        renderer.render_url("https://example.com")
    assert exc_info.value.reason == "timeout"
    page.close.assert_called_once()


def test_render_url_network_error_raises_render_error():
    renderer = PdfRenderer(paywall_text_threshold=100)
    renderer._browser = MagicMock()
    page = MagicMock()
    renderer._browser.new_page.return_value = page
    page.goto.side_effect = ConnectionError("connection refused")
    page.on.return_value = None
    with pytest.raises(RenderError) as exc_info:
        renderer.render_url("https://example.com")
    assert "network error" in exc_info.value.reason
    page.close.assert_called_once()


def test_render_url_http_error_raises_render_error():
    renderer = PdfRenderer(paywall_text_threshold=100)
    renderer._browser = MagicMock()
    page = MagicMock()
    renderer._browser.new_page.return_value = page
    page.goto.return_value = None

    def capture_listener(event, handler):
        mock_response = MagicMock()
        mock_response.url = "https://example.com"
        mock_response.status = 404
        handler(mock_response)

    page.on.side_effect = capture_listener
    with pytest.raises(RenderError) as exc_info:
        renderer.render_url("https://example.com")
    assert "http 404" in exc_info.value.reason
    page.close.assert_called_once()


def test_render_html_outer_exception_wrapped_as_render_error():
    renderer = PdfRenderer(paywall_text_threshold=100)
    renderer._browser = MagicMock()
    page = MagicMock()
    renderer._browser.new_page.return_value = page
    page.set_content.return_value = None
    page.locator.return_value.count.return_value = 0
    page.evaluate.side_effect = RuntimeError("unexpected JS failure")
    with pytest.raises(RenderError) as exc_info:
        renderer.render_html("<p>test</p>")
    assert "playwright error" in exc_info.value.reason
    page.close.assert_called_once()


def test_render_before_open_raises_runtime_error():
    renderer = PdfRenderer(paywall_text_threshold=100)
    with pytest.raises(RuntimeError, match="not open"):
        renderer.render_url("https://example.com")
    with pytest.raises(RuntimeError, match="not open"):
        renderer.render_html("<p>test</p>")


def test_context_manager_protocol():
    renderer = PdfRenderer(paywall_text_threshold=100)
    with patch.object(renderer, "open") as mock_open, \
         patch.object(renderer, "close") as mock_close:
        with renderer:
            pass
    mock_open.assert_called_once()
    mock_close.assert_called_once()
