from pathlib import Path


def test_console_is_masova_ai_and_has_no_canned_inventory_copy():
    html = Path("src/masova_agent/static/console.html").read_text()
    assert "MaSoVa AI" in html
    assert "6.2 / 10" not in html
    assert "mozz 6.2" not in html.lower()


def test_console_persists_manager_thread_for_accountability():
    """Thread journal is local; live PENDING cards also hydrate from the API."""
    html = Path("src/masova_agent/static/console.html").read_text()
    assert "localStorage" in html
    assert "function restoreThreadForStore" in html
    assert "function persistThreadNow" in html
    assert "function startNewConversation" in html
    assert "recordProposalEvent" in html
    assert "menu-new-thread" in html
    assert "chrome-btn" in html
    assert 'data-tip="New conversation"' in html
    assert "id=\"more-btn\"" not in html
    assert "masova-ai-console:thread:v1:" in html
    assert "function replayThreadEvents" in html
    assert "function restoreThreadForStore" in html
    assert "function normalizeThreadEvents" in html
    assert "function repairArchivedThreads" in html
    assert "THREAD_JOURNAL_VERSION" in html
    assert "/agent/manager/chat" in html
    assert "id=\"mic-btn\"" in html
    assert "6.2 / 10" not in html
    assert "DOM011" not in html

def test_console_prefers_gemini_audio_falls_back_to_speech_synthesis():
    """Gemini server audio plays when returned; browser speechSynthesis is the
    client-side fallback (toggleable) when no audioBase64 comes back."""
    html = Path("src/masova_agent/static/console.html").read_text()
    assert "audioBase64" in html
    assert "new Audio(" in html
    assert "speechSynthesis" in html
    assert "function speakReply" in html
    assert "id=\"tts-btn\"" in html


def test_console_polls_harness_watch_and_chain_badge():
    html = open("src/masova_agent/static/console.html", encoding="utf-8").read()
    assert "setInterval" in html
    assert "in_flight" in html
    assert "next_run_time" in html
    # Phase B: SHA-256 chain verification badge in the header bar.
    assert "id=\"chain-badge\"" in html
    assert "chain_verified" in html
    assert "function updateChainBadge" in html


def test_render_agent_rail_skips_support_chat():
    html = open("src/masova_agent/static/console.html", encoding="utf-8").read()
    assert "if (agent.id === 'support_chat') continue" in html or 'agent.id !== "support_chat"' in html or "agent.id === 'support_chat'" in html


def test_console_wakes_all_specialists_for_focus_store():
    html = Path("src/masova_agent/static/console.html").read_text()
    assert "function wakeMissingSpecialists" in html
    assert "wakeMissingSpecialists" in html
    assert "if (!restored) return wakeMissingSpecialists()" in html
    for label in (
        "Run demand",
        "Run inventory",
        "Run churn",
        "Run reviews",
        "Run shifts",
        "Run kitchen",
        "Pricing signal",
    ):
        assert label in html
    assert "cat === \"conductor\"" in html or "cat === 'conductor'" in html
    assert "return !p.store_id || p.store_id === FOCUS_STORE_ID" not in html
    assert "currentSessionId = null" in html
    assert "lastRunsByAgent[agent.id] || agent.last_run" not in html


def test_console_renders_price_lines_as_percent_off_not_inventory_qty():
    html = Path("src/masova_agent/static/console.html").read_text()
    assert "function formatProposalLineItem" in html
    assert "SUGGEST_PRICE_ADJUSTMENT" in html
    assert "'% off'" in html or '"% off"' in html
    assert "unit && current == null ? ' · ' + escapeHtml(unit)" not in html


def test_console_queues_chip_runs_and_has_decision_cards():
    html = Path("src/masova_agent/static/console.html").read_text()
    assert "function enqueueSpecialist" in html
    assert "function drainSpecialistQueue" in html
    assert "function decisionBodyHtml" in html
    assert "DRAFT_SHIFT_ROSTER" in html
    assert "metric-row" in html
    assert "--ink: #ffffff" in html


def test_console_store_proof_uses_tables_not_json_dump():
    html = Path("src/masova_agent/static/console.html").read_text()
    assert "function renderInventoryProof" in html
    assert "function renderShiftProof" in html
    assert "class=\"proof-table\"" in html or "proof-table" in html
    assert "Rendered from demo table JSON only." not in html
    assert "overflow-wrap: anywhere" not in html


def test_console_counts_only_hitl_decision_cards():
    html = Path("src/masova_agent/static/console.html").read_text()
    assert "function isHitlProposal" in html
    assert "NOTIFY_MANAGERS" in html
    assert "isHitlProposal(p)" in html
    assert "isHitlProposal(live)" in html


def test_console_renders_shift_roster_lines_with_window():
    html = Path("src/masova_agent/static/console.html").read_text()
    assert "function isShiftRosterLine" in html
    assert "DRAFT_SHIFT_ROSTER" in html
    assert "roster-day" in html
    assert "function lineItemName" in html
    assert "function hhmm" in html
    assert "item.start_time" in html
