from pathlib import Path


def test_console_is_masova_ai_and_has_no_canned_inventory_copy():
    html = Path("docs/hackathon/masova-ai-console.html").read_text()
    assert "MaSoVa AI" in html
    assert "6.2 / 10" not in html
    assert "mozz 6.2" not in html.lower()
