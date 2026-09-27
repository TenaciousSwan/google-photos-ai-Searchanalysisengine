import pytest
from fastapi.testclient import TestClient
from backend.main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def test_root_and_health_endpoints(client):
    """Verify root index, health, and LLM status endpoints."""
    # Root
    r_root = client.get("/")
    assert r_root.status_code == 200
    data_root = r_root.json()
    assert "engine" in data_root
    assert data_root["docs"] == "/docs"

    # Health
    r_health = client.get("/api/v1/health")
    assert r_health.status_code == 200
    data_health = r_health.json()
    assert data_health["status"] == "healthy"
    assert data_health["database"] == "connected"

    # LLM Status
    r_llm = client.get("/api/v1/llm/status")
    assert r_llm.status_code == 200
    data_llm = r_llm.json()
    assert "ollama_available" in data_llm
    assert "gemini_tokens_available" in data_llm

def test_metrics_overview_global_and_platform_filter(client):
    """Verify overview metrics endpoint with and without platform filter."""
    # Global
    r_global = client.get("/api/v1/metrics/overview")
    assert r_global.status_code == 200
    data_global = r_global.json()
    assert "total_conversations" in data_global
    assert "system_failure_rate" in data_global
    assert "average_severity" in data_global
    assert "platforms_represented" in data_global

    # Filtered by Android
    r_android = client.get("/api/v1/metrics/overview?platform=android")
    assert r_android.status_code == 200
    data_android = r_android.json()
    assert data_android["platforms_represented"] == ["android"]
    assert data_android["total_conversations"] <= data_global["total_conversations"]

def test_problems_listing_and_filtering(client):
    """Verify problems list, priority tier filtering, and platform filtering."""
    # All problems
    r_all = client.get("/api/v1/problems")
    assert r_all.status_code == 200
    problems = r_all.json()
    assert isinstance(problems, list)
    assert len(problems) >= 1

    cluster_id = problems[0]["id"]

    # Filter by tier
    r_tier = client.get("/api/v1/problems?tier=CRITICAL")
    assert r_tier.status_code == 200
    crit_problems = r_tier.json()
    assert all(p["opportunity_tier"] == "CRITICAL" for p in crit_problems)

    # Filter by platform
    r_platform = client.get("/api/v1/problems?platform=android")
    assert r_platform.status_code == 200
    assert isinstance(r_platform.json(), list)

    # Problem Detail
    r_detail = client.get(f"/api/v1/problems/{cluster_id}")
    assert r_detail.status_code == 200
    detail = r_detail.json()
    assert detail["id"] == cluster_id
    assert "product_insight" in detail

    # Nonexistent Problem (404)
    r_404 = client.get("/api/v1/problems/nonexistent_cluster_999")
    assert r_404.status_code == 404

def test_traceability_and_evidence_endpoints(client):
    """Verify bidirectional Evidence Traceability Graph and paginated evidence retrieval."""
    r_probs = client.get("/api/v1/problems")
    cluster_id = r_probs.json()[0]["id"]

    # Traceability Graph
    r_trace = client.get(f"/api/v1/problems/{cluster_id}/traceability")
    assert r_trace.status_code == 200
    trace = r_trace.json()
    assert "cluster" in trace
    assert "verbatim_evidence" in trace
    assert "traceability_integrity" in trace
    assert trace["traceability_integrity"]["verified_quotes_count"] > 0

    # Evidence List
    r_ev = client.get(f"/api/v1/problems/{cluster_id}/evidence?limit=5")
    assert r_ev.status_code == 200
    ev_list = r_ev.json()
    assert isinstance(ev_list, list)
    assert len(ev_list) > 0
    assert "raw_text" in ev_list[0]
    assert "author_pseudonym" in ev_list[0]

def test_score_matrix_and_journey_graph(client):
    """Verify Opportunity Matrix data and 4-stage Cognitive Journey Flow."""
    # Score Matrix
    r_matrix = client.get("/api/v1/score/matrix")
    assert r_matrix.status_code == 200
    matrix = r_matrix.json()
    assert isinstance(matrix, list)
    assert len(matrix) >= 1
    item = matrix[0]
    for field in ("id", "cluster_name", "failure_rate", "evidence_count", "average_severity", "opportunity_tier"):
        assert field in item

    # Journey Graph
    r_journey = client.get("/api/v1/journey/graph")
    assert r_journey.status_code == 200
    journey = r_journey.json()
    assert "nodes" in journey
    assert "links" in journey
    assert "summary" in journey
    assert len(journey["nodes"]) > 0
    assert len(journey["links"]) > 0

def test_insights_cards_and_discovery_brief(client):
    """Verify Product Discovery Cards and 10-Question PM Discovery Report."""
    # Discovery Cards
    r_cards = client.get("/api/v1/insights/cards")
    assert r_cards.status_code == 200
    cards = r_cards.json()
    assert isinstance(cards, list)
    assert len(cards) >= 1
    card = cards[0]
    assert "user_memory_pattern" in card
    assert "retrieval_pattern" in card
    assert "failure_pattern" in card
    assert "opportunity_statement" in card
    assert "recommended_feature_direction" in card

    # Single card
    cluster_id = card["cluster_id"]
    r_single = client.get(f"/api/v1/insights/cards/{cluster_id}")
    assert r_single.status_code == 200
    assert r_single.json()["cluster_id"] == cluster_id

    # 10-Question Report
    r_report = client.get("/api/v1/report/discovery-brief")
    assert r_report.status_code == 200
    report = r_report.json()
    assert "questions" in report
    assert len(report["questions"]) == 10
    assert "markdown_report" in report
    assert "# Google Photos Strategic Product Discovery Report" in report["markdown_report"]

def test_openapi_documentation(client):
    """Verify OpenAPI 3.x schema generation and documentation endpoints."""
    # OpenAPI JSON Schema
    r_openapi = client.get("/openapi.json")
    assert r_openapi.status_code == 200
    schema = r_openapi.json()
    assert "openapi" in schema
    assert "paths" in schema
    # Check that key paths are documented
    paths = schema["paths"]
    assert "/api/v1/metrics/overview" in paths
    assert "/api/v1/problems" in paths
    assert "/api/v1/problems/{cluster_id}/traceability" in paths
    assert "/api/v1/journey/graph" in paths
    assert "/api/v1/report/discovery-brief" in paths

    # Swagger Docs HTML
    r_docs = client.get("/docs")
    assert r_docs.status_code == 200
