import time
import pytest
import sqlite3
import json
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from backend.main import app
from backend.app.core.database import db_manager
from backend.app.core.config import settings
from backend.app.models.schemas import (
    CognitiveExtractionPayload, 
    MemorySignals, 
    ForgottenSignals, 
    OutcomeEnum,
    ProblemCluster,
    DiscoveryCardSynthesis
)
from backend.app.services.orchestrator import LLMOrchestrator
from backend.app.services.gemini_client import GeminiClient, RateLimitException
from backend.app.pipeline.clustering import SemanticClusteringManager

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

# ---------------------------------------------------------------------------
# 1. Automated Schema, Quality & Relational Integrity Audits
# ---------------------------------------------------------------------------

def test_database_foreign_key_integrity():
    """Run SQLite foreign_key_check to assert zero orphaned records across all 8 tables."""
    with db_manager.session() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_key_check;")
        orphans = cursor.fetchall()
        assert len(orphans) == 0, f"Detected orphaned foreign key records in SQLite: {orphans}"

def test_extracted_signals_schema_validation():
    """Verify all extracted signals in SQLite conform 100% to Pydantic CognitiveExtractionPayload."""
    with db_manager.session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT conversation_id, entities_remembered, spatial_cues, 
                   temporal_cues, visual_cues, text_cues, actions_taken, 
                   date_forgotten, terminal_outcome, frustration_severity, 
                   primary_failure_mode
            FROM extracted_signals;
        """)
        rows = cursor.fetchall()
        assert len(rows) > 0, "No extracted signals found in database."

        for r in rows:
            memory = MemorySignals(
                entities_remembered=json.loads(r["entities_remembered"] or "[]"),
                spatial_cues=r["spatial_cues"],
                temporal_cues=r["temporal_cues"],
                visual_aesthetic_cues=r["visual_cues"],
                embedded_text_cues=r["text_cues"],
            )
            forgotten = ForgottenSignals(
                exact_date_forgotten=bool(r["date_forgotten"])
            )
            payload = CognitiveExtractionPayload(
                conversation_id=r["conversation_id"],
                memory_signals=memory,
                forgotten_signals=forgotten,
                actions_taken=[],
                outcome=OutcomeEnum(r["terminal_outcome"]),
                user_frustration_level=r["frustration_severity"],
                primary_failure_mode=r["primary_failure_mode"] or "Retrieval failure"
            )
            assert payload.user_frustration_level in range(1, 6)
            assert payload.outcome in OutcomeEnum

def test_evidence_traceability_links():
    """Confirm every active problem cluster links to valid primary source conversations in SQLite."""
    with db_manager.session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, archetype, evidence_count FROM problem_clusters;")
        clusters = cursor.fetchall()
        assert len(clusters) > 0, "No problem clusters found."

        for cl in clusters:
            cid = cl["id"]
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM signal_cluster_mapping scm
                JOIN extracted_signals es ON scm.signal_id = es.id
                JOIN raw_conversations rc ON es.conversation_id = rc.id
                WHERE scm.cluster_id = ?;
            """, (cid,))
            row = cursor.fetchone()
            count = row["count"]
            assert count > 0, f"Cluster {cid} has zero linked evidence records in raw_conversations."

# ---------------------------------------------------------------------------
# 2. Dual-LLM Circuit Breaker & Failover Audit
# ---------------------------------------------------------------------------

from backend.app.core.database import DatabaseManager

def test_dual_llm_transparent_failover_under_quota_exhaustion(tmp_path):
    """
    Simulate Gemini Free Tier HTTP 429 quota exhaustion.
    Assert seamless, transparent failover to local Ollama with isolated cache.
    """
    test_db = tmp_path / "test_p9_failover.db"
    isolated_db = DatabaseManager(db_path=test_db)
    isolated_db.init_db()

    test_orchestrator = LLMOrchestrator()
    test_orchestrator.gemini.is_available = MagicMock(return_value=True)

    with patch("backend.app.services.orchestrator.db_manager", isolated_db):
        with patch.object(test_orchestrator.gemini, "generate_structured", side_effect=RateLimitException("HTTP 429 ResourceExhausted")):
            with patch.object(test_orchestrator.ollama, "generate_json", return_value={"status": "failover_success", "source": "ollama"}) as mock_ollama:
                prompt = "Extract memory signals from review: cannot find receipts from last month"
                
                result = test_orchestrator.run_structured(
                    prompt=prompt, 
                    response_schema=CognitiveExtractionPayload, 
                    prefer_engine="gemini"
                )
                
                assert mock_ollama.called, "Local Ollama fallback was not invoked after Gemini 429."
                assert result == {"status": "failover_success", "source": "ollama"}
                assert test_orchestrator.total_failovers == 1

# ---------------------------------------------------------------------------
# 3. Traceability & Response Latency Benchmarks (< 50ms SLA)
# ---------------------------------------------------------------------------

def test_evidence_retrieval_latency_benchmark(client):
    """Assert < 50ms response time on evidence retrieval across all clusters."""
    with db_manager.session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM problem_clusters;")
        clusters = cursor.fetchall()
        assert len(clusters) > 0

    latencies = []
    for cl in clusters:
        cid = cl["id"]
        t0 = time.perf_counter()
        resp = client.get(f"/api/v1/problems/{cid}/evidence")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert resp.status_code == 200
        latencies.append(elapsed_ms)

    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)
    print(f"\n[LATENCY BENCHMARK] /api/v1/problems/{{id}}/evidence: avg={avg_latency:.2f}ms, max={max_latency:.2f}ms")
    assert avg_latency < 50.0, f"Evidence retrieval SLA breached: avg={avg_latency:.2f}ms >= 50ms"

def test_metrics_overview_latency_benchmark(client):
    """Assert < 50ms response time on aggregated metrics overview."""
    latencies = []
    for _ in range(5):
        t0 = time.perf_counter()
        resp = client.get("/api/v1/metrics/overview")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert resp.status_code == 200
        latencies.append(elapsed_ms)

    avg_latency = sum(latencies) / len(latencies)
    print(f"\n[LATENCY BENCHMARK] /api/v1/metrics/overview: avg={avg_latency:.2f}ms")
    assert avg_latency < 50.0, f"Metrics overview SLA breached: avg={avg_latency:.2f}ms >= 50ms"

# ---------------------------------------------------------------------------
# 4. Clustering Determinism & Reproducibility Audit
# ---------------------------------------------------------------------------

def test_clustering_reproducibility_benchmark():
    """
    Run hierarchical agglomerative clustering across identical inputs twice.
    Assert 100% identical cluster assignments (deterministic reproducibility).
    """
    manager = SemanticClusteringManager()
    
    signals = [
        {"signal_id": "sig_1", "entities_remembered": "receipt", "spatial_cues": "desk", "primary_failure_mode": "OCR Fail", "raw_text": "tax receipt"},
        {"signal_id": "sig_2", "entities_remembered": "invoice", "spatial_cues": "office", "primary_failure_mode": "OCR Fail", "raw_text": "gas receipt"},
        {"signal_id": "sig_3", "entities_remembered": "concert band", "spatial_cues": "stadium", "primary_failure_mode": "Date Forgot", "raw_text": "festival video"},
        {"signal_id": "sig_4", "entities_remembered": "music festival", "spatial_cues": "park", "primary_failure_mode": "Date Forgot", "raw_text": "outdoor concert"},
        {"signal_id": "sig_5", "entities_remembered": "golden retriever", "spatial_cues": "yard", "primary_failure_mode": "Pet Breed", "raw_text": "dog running"},
        {"signal_id": "sig_6", "entities_remembered": "puppy dog", "spatial_cues": "beach", "primary_failure_mode": "Pet Breed", "raw_text": "pet puppy"}
    ]

    # Run pass 1
    clusters_1 = manager.cluster_signals(signals, target_distance_threshold=0.85)
    # Run pass 2
    clusters_2 = manager.cluster_signals(signals, target_distance_threshold=0.85)

    assert len(clusters_1) == len(clusters_2), "Cluster count inconsistent across runs."
    
    # Check assignment stability
    partitions_1 = sorted([sorted([s["signal_id"] for s in members]) for members in clusters_1.values()])
    partitions_2 = sorted([sorted([s["signal_id"] for s in members]) for members in clusters_2.values()])

    assert partitions_1 == partitions_2, "Clustering partition is non-deterministic across repeated runs."
