# tests/test_url_detector.py
import pytest
from email_reader.url_detector import (
    visible_text_length,
    is_blocked,
    score_links,
    inline_cid_images,
    wrap_html,
    detect_content,
    ContentResult,
)

_MIXED_HTML = (
    '<p>See <a href="https://article.com">Read this important geopolitics piece</a>'
    ' and <a href="https://unsubscribe.com">Unsubscribe</a></p>'
)


def test_visible_text_length_counts_text_only():
    assert visible_text_length("<p>Hello world</p>") == 11


def test_visible_text_length_excludes_tags():
    length = visible_text_length("<div><p>One</p><p>Two</p></div>")
    assert length == 7  # "One Two" (space-separated)


def test_is_blocked_matches_substring():
    assert is_blocked("https://example.com/page", ["example.com"]) is True


def test_is_blocked_no_match():
    assert is_blocked("https://good.com/page", ["example.com"]) is False


def test_is_blocked_empty_list():
    assert is_blocked("https://any.com", []) is False


def test_score_links_picks_highest_anchor_text():
    links = score_links(_MIXED_HTML, blocklist=[])
    # "Read this important geopolitics piece" is longer than "Unsubscribe"
    assert links[0][0] == "https://article.com"


def test_score_links_excludes_blocked_urls():
    links = score_links(_MIXED_HTML, blocklist=["unsubscribe.com"])
    hrefs = [link[0] for link in links]
    assert "https://unsubscribe.com" not in hrefs


def test_score_links_excludes_non_http_hrefs():
    html = '<a href="mailto:foo@bar.com">Email me</a><a href="https://ok.com">Click</a>'
    links = score_links(html, blocklist=[])
    assert all(link[0].startswith("http") for link in links)
    assert len(links) == 1


def test_detect_content_url_mode_for_short_body():
    html = '<p>See <a href="https://article.com">Read this important geopolitics piece</a></p>'
    result = detect_content(html, {}, url_detection_threshold=500, blocklist=[])
    assert result.source == "url"
    assert result.url == "https://article.com"


def test_detect_content_body_mode_for_long_body():
    long_body = "<p>" + ("word " * 200) + "</p>"
    result = detect_content(long_body, {}, url_detection_threshold=500, blocklist=[])
    assert result.source == "body"
    assert result.url is None
    assert "<!DOCTYPE html>" in result.html


def test_detect_content_falls_back_to_body_when_all_links_blocked():
    html = '<p>See <a href="https://blocked.com">Read article here now</a></p>'
    result = detect_content(html, {}, url_detection_threshold=500, blocklist=["blocked.com"])
    assert result.source == "body"


def test_inline_cid_images_replaces_src():
    html = '<img src="cid:image001">'
    cid_map = {"image001": b"\x89PNG\r\n"}
    result = inline_cid_images(html, cid_map)
    assert "cid:image001" not in result
    assert "data:image/png;base64," in result


def test_wrap_html_produces_standalone_document():
    wrapped = wrap_html("<p>Content</p>")
    assert "<!DOCTYPE html>" in wrapped
    assert "<p>Content</p>" in wrapped
    assert 'charset="utf-8"' in wrapped


def test_content_result_has_expected_fields():
    r = ContentResult(source="url", url="https://x.com", html="<p>hi</p>")
    assert r.source == "url"
    assert r.url == "https://x.com"
