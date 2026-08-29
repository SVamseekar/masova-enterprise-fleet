from pathlib import Path


def test_console_is_masova_ai_and_has_no_canned_inventory_copy():
    html = Path("docs/hackathon/masova-ai-console.html").read_text()
    assert "MaSoVa AI" in html
    assert "6.2 / 10" not in html
    assert "mozz 6.2" not in html.lower()


def test_console_persists_manager_thread_for_accountability():
    """Thread journal is local; live PENDING cards also hydrate from the API."""
    html = Path("docs/hackathon/masova-ai-console.html").read_text()
    assert "localStorage" in html
    assert "function restoreThreadForStore" in html
    assert "function persistThreadNow" in html
    assert "function startNewConversation" in html
    assert "recordProposalEvent" in html
    assert "menu-new-thread" in html
    assert "masova-ai-console:thread:v1:" in html
    assert "refreshProposalsIntoThread(null" in html
    assert "/agent/manager/chat" in html
    assert "id=\"mic-btn\"" in html
    assert "6.2 / 10" not in html
    assert "DOM011" not in html

def test_console_plays_gemini_audio_not_speech_synthesis():
    html = Path("docs/hackathon/masova-ai-console.html").read_text()
    assert "audioBase64" in html
    assert "speechSynthesis" not in html
    assert "new Audio(" in html
