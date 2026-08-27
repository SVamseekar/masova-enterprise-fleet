# tests/test_proposal_reject_apply.py
def test_apply_rejected_proposal_importable_and_cancels_draft_po(tmp_path, monkeypatch):
    from masova_agent.runtime import proposal_apply
    assert hasattr(proposal_apply, "apply_rejected_proposal")
