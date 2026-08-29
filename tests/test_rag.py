"""Operations RAG — lexical CI fallback, no live embeddings."""
import pytest


@pytest.mark.asyncio
async def test_search_ops_manual_hits_haccp_cooler(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from masova_agent.knowledge.rag import search_ops_manual

    out = await search_ops_manual("cooler temperature")
    assert out["ok"] is True
    blob = " ".join(h["text"] for h in out["hits"]).lower()
    assert "cooler" in blob or "celsius" in blob or "temp" in blob


def test_search_ops_manual_registered_as_manager_read_tool():
    from masova_agent.agents.manager_chat_agent import MANAGER_TOOLS
    from masova_agent.runtime.policy import DEFAULT_TOOL_REGISTRY, RiskTier

    assert "search_ops_manual" in MANAGER_TOOLS
    assert DEFAULT_TOOL_REGISTRY["search_ops_manual"].tier == RiskTier.READ
