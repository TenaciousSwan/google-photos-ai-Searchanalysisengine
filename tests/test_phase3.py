import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from backend.app.models.schemas import (
    CognitiveExtractionPayload,
    MemorySignals,
    ForgottenSignals,
    RetrievalAction,
    OutcomeEnum
)
from backend.app.pipeline.extraction import (
    CognitiveSignalExtractor,
    ExtractionPipelineManager
)
from backend.app.core.database import DatabaseManager

def test_cognitive_extractor_schema_structure():
    """Verify that structured extraction adheres strictly to Pydantic schema."""
    payload = CognitiveExtractionPayload(
        conversation_id="test_001",
        memory_signals=MemorySignals(
            entities_remembered=["dog", "red birthday hat"],
            spatial_cues="living room",
            temporal_cues="last December",
            visual_aesthetic_cues="red hat on golden fur",
            embedded_text_cues=None
        ),
        forgotten_signals=ForgottenSignals(
            exact_date_forgotten=True,
            exact_location_forgotten=False,
            filename_forgotten=True,
            album_name_forgotten=True
        ),
        actions_taken=[
            RetrievalAction(action_type="text_query", query_string="dog"),
            RetrievalAction(action_type="manual_scroll", query_string=None)
        ],
        outcome=OutcomeEnum.FAILED_IRRELEVANT,
        user_frustration_level=4,
        primary_failure_mode="Oversaturation / Low Precision"
    )
    assert payload.conversation_id == "test_001"
    assert payload.outcome == OutcomeEnum.FAILED_IRRELEVANT
    assert payload.user_frustration_level == 4
    assert len(payload.memory_signals.entities_remembered) == 2

def test_sarcastic_review_extraction_handling():
    """
    Edge Case 3.1:
    Verify that sarcastic review ('Brilliant search!') is parsed as
    action -> expectation -> failure rather than positive sentiment.
    """
    extractor = CognitiveSignalExtractor()
    mock_payload = {
        "conversation_id": "test_sarcasm",
        "memory_signals": {
            "entities_remembered": ["my car", "yellow house"],
            "spatial_cues": "in front of the yellow house",
            "temporal_cues": "last summer",
            "visual_aesthetic_cues": "car in front of yellow house",
            "embedded_text_cues": None
        },
        "forgotten_signals": {
            "exact_date_forgotten": True,
            "exact_location_forgotten": True,
            "filename_forgotten": True,
            "album_name_forgotten": False
        },
        "actions_taken": [
            {"action_type": "text_query", "query_string": "car"}
        ],
        "outcome": "FAILED_IRRELEVANT",
        "user_frustration_level": 5,
        "primary_failure_mode": "Visual-Concept Search Gap"
    }

    with patch("backend.app.pipeline.extraction.orchestrator.run_structured", return_value=mock_payload):
        result = extractor.extract_from_text("test_sarcasm", "Brilliant search! Found 5000 random white cars...")
        assert result.outcome == OutcomeEnum.FAILED_IRRELEVANT
        assert result.user_frustration_level == 5
        assert "my car" in result.memory_signals.entities_remembered

def test_extraction_batch_pipeline_execution(tmp_path):
    """
    Test end-to-end extraction batch:
      1. Inserts mock qualified conversations.
      2. Runs extraction_manager.run_extraction_batch().
      3. Verifies extracted_signals table populated with relational foreign keys.
    """
    test_db = tmp_path / "test_extract.db"
    db = DatabaseManager(db_path=test_db)
    db.init_db()

    with db.session() as conn:
        conn.execute(
            """
            INSERT INTO raw_conversations (id, source, post_date, platform, raw_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("conv_extract_1", "play_store", "2024-03-01", "android", "Searching for prescription from last winter.")
        )
        conn.execute(
            """
            INSERT INTO conversation_qualifications (conversation_id, is_retrieval_friction, confidence_score, filter_reason)
            VALUES (?, ?, ?, ?)
            """,
            ("conv_extract_1", 1, 0.95, "Prescription document struggle")
        )

    mock_extract_data = {
        "conversation_id": "conv_extract_1",
        "memory_signals": {
            "entities_remembered": ["doctor's prescription"],
            "spatial_cues": None,
            "temporal_cues": "last winter",
            "visual_aesthetic_cues": None,
            "embedded_text_cues": "prescription medicine"
        },
        "forgotten_signals": {
            "exact_date_forgotten": True,
            "exact_location_forgotten": True,
            "filename_forgotten": True,
            "album_name_forgotten": True
        },
        "actions_taken": [
            {"action_type": "text_query", "query_string": "prescription"},
            {"action_type": "manual_scroll", "query_string": None}
        ],
        "outcome": "SUCCESS_EVENTUAL",
        "user_frustration_level": 4,
        "primary_failure_mode": "Utility / Document Retrieval Gap"
    }

    with patch("backend.app.pipeline.extraction.db_manager", db):
        with patch("backend.app.pipeline.extraction.orchestrator.run_structured", return_value=mock_extract_data):
            manager = ExtractionPipelineManager()
            res = manager.run_extraction_batch()
            assert res["total_candidates"] == 1
            assert res["successfully_extracted"] == 1

            # Verify SQLite row
            with db.session() as conn:
                row = conn.execute("SELECT * FROM extracted_signals WHERE conversation_id = 'conv_extract_1'").fetchone()
                assert row is not None
                assert row["terminal_outcome"] == "SUCCESS_EVENTUAL"
                assert row["primary_failure_mode"] == "Utility / Document Retrieval Gap"
                assert row["frustration_severity"] == 4
