# tests/test_pdf.py
import pytest
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
