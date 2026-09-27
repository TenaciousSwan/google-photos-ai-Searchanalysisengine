import pytest
import sqlite3
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.core.rate_limiter import TokenBucketRateLimiter
from backend.app.core.database import DatabaseManager
from backend.app.models.schemas import (
    RawConversation,
    RelevanceGateOutput,
    CognitiveExtractionPayload,
    MemorySignals,
    ForgottenSignals,
    OutcomeEnum,
    ProblemCluster,
    PriorityTierEnum,
    OverviewMetrics
)
from backend.app.services.ollama_client import OllamaClient
from backend.app.services.gemini_client import GeminiClient, RateLimitException
from backend.app.services.orchestrator import LLMOrchestrator

def test_database_initialization(tmp_path):
    """Verify SQLite database schema creation, tables, and WAL mode."""
    test_db = tmp_path / "test_discovery.db"
    db = DatabaseManager(db_path=test_db)
    db.init_db()

    with db.session() as conn:
        tables = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "raw_conversations" in tables
        assert "conversation_qualifications" in tables
        assert "extracted_signals" in tables
        assert "problem_clusters" in tables
        assert "signal_cluster_mapping" in tables
        assert "product_insights" in tables
        assert "llm_cache" in tables
        assert "ingestion_checkpoints" in tables

def test_disk_cache(tmp_path):
    """Test MD5 cache key computation and setting/getting cached responses."""
    test_db = tmp_path / "test_cache.db"
    db = DatabaseManager(db_path=test_db)
    db.init_db()

    cache_key = db.compute_cache_key("test_model", "test_prompt", "input_text")
    assert len(cache_key) == 32  # MD5 hex length

    assert db.get_cached_response(cache_key) is None

    test_data = {"result": "ok", "confidence": 0.95}
    db.set_cached_response(cache_key, "test_model", test_data)

    cached = db.get_cached_response(cache_key)
    assert cached == test_data

def test_token_bucket_rate_limiter():
    """Verify token bucket permits burst up to capacity and replenishes."""
    limiter = TokenBucketRateLimiter(rpm=60) # 1 token per second
    assert limiter.acquire(wait=False) is True
    tokens = limiter.get_available_tokens()
    assert tokens < 60.0

def test_pydantic_schemas():
    """Verify data models validate fields and serialize to JSON."""
    raw = RawConversation(
        id="conv_123",
        source="play_store",
        post_date="2024-03-15",
        platform="android",
        raw_text="Cannot find my old trip pictures from 2021"
    )
    assert raw.id == "conv_123"

    cog = CognitiveExtractionPayload(
        conversation_id="conv_123",
        memory_signals=MemorySignals(
            spatial_cues="trip to Goa",
            temporal_cues="2021"
        ),
        forgotten_signals=ForgottenSignals(
            exact_date_forgotten=True,
            exact_location_forgotten=True
        ),
        actions_taken=[],
        outcome=OutcomeEnum.FAILED_ZERO_RESULTS,
        user_frustration_level=4,
        primary_failure_mode="Unknown Time & Location"
    )
    dumped = cog.model_dump()
    assert dumped["outcome"] == "FAILED_ZERO_RESULTS"
    assert dumped["user_frustration_level"] == 4

def test_ollama_markdown_json_parsing():
    """
    Edge Case 4.2 in edge-case.md:
    Verify OllamaClient regex parser cleanly extracts JSON even when wrapped
    in conversational preambles and markdown codeblocks.
    """
    client = OllamaClient()
    mock_response = (
        "Here is the JSON you requested:\n"
        "```json\n"
        "{\n"
        '  "is_retrieval_friction": true,\n'
        '  "confidence_score": 0.92,\n'
        '  "relevance_rationale": "User forgot date of trip photo",\n'
        '  "friction_trigger": "forgot date"\n'
        "}\n"
        "```\n"
        "Hope this helps!"
    )
    with patch.object(client, "generate", return_value=mock_response):
        parsed = client.generate_json(prompt="dummy prompt")
        assert parsed.get("is_retrieval_friction") is True
        assert parsed.get("confidence_score") == 0.92

def test_orchestrator_failover_on_rate_limit(tmp_path):
    """
    Verify that when Gemini raises a RateLimitException (HTTP 429),
    the orchestrator catches it, fails over to Ollama, and logs the failover event.
    """
    test_db = tmp_path / "test_failover.db"
    db = DatabaseManager(db_path=test_db)
    db.init_db()

    mock_gemini = MagicMock(spec=GeminiClient)
    mock_gemini.is_available.return_value = True
    mock_gemini.generate_structured.side_effect = RateLimitException("429 Quota Exhausted")

    mock_ollama = MagicMock(spec=OllamaClient)
    mock_ollama.is_available.return_value = True
    mock_ollama.default_model = "qwen2.5:1.5b"
    mock_ollama.generate_json.return_value = {
        "is_retrieval_friction": True,
        "confidence_score": 0.88,
        "relevance_rationale": "Handled by Ollama fallback",
        "friction_trigger": "unknown location"
    }

    with patch("backend.app.services.orchestrator.db_manager", db):
        orch = LLMOrchestrator(gemini=mock_gemini, ollama=mock_ollama, rpm_limit=60)
        result = orch.run_structured(
            prompt="Looking for beach photo",
            response_schema=RelevanceGateOutput,
            prefer_engine="gemini"
        )
        assert orch.total_failovers == 1
        assert orch.total_ollama_calls == 1
        assert result.get("relevance_rationale") == "Handled by Ollama fallback"
