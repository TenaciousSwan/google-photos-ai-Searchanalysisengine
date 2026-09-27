import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.main import app
from backend.app.services.qa_engine import qa_engine, extract_keywords

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def test_extract_keywords():
    """Verify that stop words are filtered and keywords are properly extracted."""
    kws = extract_keywords("Why can't people find their doctor prescriptions or receipt photos?")
    assert "prescriptions" in kws
    assert "receipt" in kws
    assert "why" not in kws
    assert "the" not in kws

def test_search_relevant_reviews():
    """Verify retrieval pulls relevant real reviews matching keywords."""
    reviews = qa_engine.search_relevant_reviews("prescription medicine doctor", limit=5)
    assert len(reviews) > 0
    assert "id" in reviews[0]
    assert "raw_text" in reviews[0]
    assert "platform" in reviews[0]

def test_ask_endpoint_success(client):
    """Verify /api/v1/ask returns a valid answer and supporting source reviews."""
    res = client.post("/api/v1/ask", json={"question": "Why can't users find prescription photos?"})
    assert res.status_code == 200
    data = res.json()
    assert "question" in data
    assert "answer" in data
    assert "sources" in data
    assert len(data["answer"]) > 10
    assert len(data["sources"]) > 0
    assert "id" in data["sources"][0]
    assert "raw_text" in data["sources"][0]

def test_ask_endpoint_empty_question(client):
    """Verify empty question yields a 400 status code."""
    res = client.post("/api/v1/ask", json={"question": "   "})
    assert res.status_code == 400

def test_stub_fallback_when_llm_unavailable():
    """Verify grounded stub fallback produces realistic answer citing real IDs when LLM returns empty."""
    with patch("backend.app.services.orchestrator.orchestrator.gemini.is_available", return_value=False), \
         patch("backend.app.services.orchestrator.orchestrator.ollama.is_available", return_value=False):
        result = qa_engine.answer_question("Why are dates on downloaded photos wrong?")
        assert result["question"] == "Why are dates on downloaded photos wrong?"
        assert len(result["sources"]) > 0
        # Check that answer contains Review ID citations from the sources
        first_id = result["sources"][0]["id"]
        assert first_id in result["answer"]
