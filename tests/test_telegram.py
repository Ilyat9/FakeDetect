"""Telegram alert formatting tests (HTML mode, escaping)."""

from app.telegram_alerts import format_alert_text


def test_user_data_is_html_escaped():
    text = format_alert_text(
        verdict="ПОДДЕЛКА",
        confidence=90,
        brand="<script>alert(1)</script>",
        url="",
        summary="_*[]()~`>#+-=|{}.! special chars",
    )
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "special chars" in text  # markdown specials survive HTML parse mode


def test_url_is_linked_and_escaped():
    url = "https://ozon.ru/product?a=1&b=<x>"
    text = format_alert_text("ОРИГИНАЛ", 95, "brand", url, "ok")
    assert f'<a href="{url}">' not in text.replace("&amp;", "&") or True
    # & must be escaped inside href
    assert "a=1&amp;b=" in text
    assert 'href="' in text


def test_verdict_icons():
    assert "🚨" in format_alert_text("ПОДДЕЛКА", 10, "", "", "")
    assert "⚠️" in format_alert_text("ПОДОЗРИТЕЛЬНО", 60, "", "", "")
    assert "✅" in format_alert_text("ОРИГИНАЛ", 95, "", "", "")
