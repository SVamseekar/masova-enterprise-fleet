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

def test_console_prefers_gemini_audio_falls_back_to_speech_synthesis():
    """Gemini server audio plays when returned; browser speechSynthesis is the
    client-side fallback (toggleable) when no audioBase64 comes back."""
    html = Path("docs/hackathon/masova-ai-console.html").read_text()
    assert "audioBase64" in html
    assert "new Audio(" in html
    assert "speechSynthesis" in html
    assert "function speakReply" in html
    assert "id=\"tts-btn\"" in html


def test_console_polls_harness_watch_and_chain_badge():
    html = open("docs/hackathon/masova-ai-console.html", encoding="utf-8").read()
    assert "setInterval" in html
    assert "in_flight" in html
    assert "next_run_time" in html
    # Phase B: SHA-256 chain verification badge in the header bar.
    assert "id=\"chain-badge\"" in html
    assert "chain_verified" in html
    assert "function updateChainBadge" in html


def test_render_agent_rail_skips_support_chat():
    html = open("docs/hackathon/masova-ai-console.html", encoding="utf-8").read()
    assert "if (agent.id === 'support_chat') continue" in html or 'agent.id !== "support_chat"' in html or "agent.id === 'support_chat'" in html
