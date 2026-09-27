import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.pipeline.relevance import (
    HeuristicRelevanceFilter,
    RelevancePipelineManager
)
from backend.app.models.schemas import RelevanceGateOutput
from backend.app.core.database import DatabaseManager

def test_heuristic_filter_rejections():
    """Verify Layer 1 fast heuristic immediately drops pure battery, billing, and shipping noise."""
    # Pure battery drain
    res_batt, reason_batt = HeuristicRelevanceFilter.evaluate("This app drains my phone battery in two hours during background backup.")
    assert res_batt is False
    assert "Battery" in reason_batt

    # Pure Google One billing
    res_bill, reason_bill = HeuristicRelevanceFilter.evaluate("My Google One storage tier subscription charged my credit card twice. Requesting refund.")
    assert res_bill is False
    assert "Billing" in reason_bill

    # Pure print store shipping
    res_ship, reason_ship = HeuristicRelevanceFilter.evaluate("My photo book canvas order arrived with damaged print book shipping.")
    assert res_ship is False
    assert "Print Store" in reason_ship

def test_heuristic_filter_retrieval_pass():
    """Verify genuine photo search struggle passes through Layer 1 to Layer 2."""
    res_ok, reason_ok = HeuristicRelevanceFilter.evaluate("I was looking for a picture of my doctor's prescription from last winter but couldn't find it.")
    assert res_ok is None
    assert "LLM" in reason_ok

def test_mixed_intent_detection():
    """
    Edge Case 2.3:
    Review mentions billing/battery but ALSO mentions photo search struggle.
    Heuristic should NOT reject it prematurely; must defer to LLM.
    """
    mixed_text = "I pay for Google One storage tier, but the search doesn't even find my vacation photos from last summer!"
    res_mixed, reason_mixed = HeuristicRelevanceFilter.evaluate(mixed_text)
    assert res_mixed is None
    assert "Mixed-intent" in reason_mixed

def test_relevance_pipeline_batch_execution(tmp_path):
    """
    Test end-to-end qualification pipeline:
      1. Inserts mock conversations into raw_conversations.
      2. Runs run_qualification_batch.
      3. Verifies conversation_qualifications populated with correct flags.
    """
    test_db = tmp_path / "test_qualify.db"
    db = DatabaseManager(db_path=test_db)
    db.init_db()

    with db.session() as conn:
        # 1 retrieval friction
        conn.execute(
            """
            INSERT INTO raw_conversations (id, source, post_date, platform, raw_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("conv_01", "play_store", "2024-03-01", "android", "Can't find my doctor's prescription paper from last winter.")
        )
        # 1 pure noise
        conn.execute(
            """
            INSERT INTO raw_conversations (id, source, post_date, platform, raw_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("conv_02", "app_store", "2024-03-02", "ios", "Horrible battery drain on iPhone while charging.")
        )

    # Mock orchestrator classification for conv_01
    mock_llm_output = RelevanceGateOutput(
        is_retrieval_friction=True,
        confidence_score=0.95,
        relevance_rationale="User searching for prescription with unknown date",
        friction_trigger="prescription document"
    )

    with patch("backend.app.pipeline.relevance.db_manager", db):
        with patch("backend.app.pipeline.relevance.orchestrator.classify_relevance", return_value=mock_llm_output):
            manager = RelevancePipelineManager()
            result = manager.run_qualification_batch()

            assert result["total_processed"] == 2
            assert result["qualified_retrieval_friction"] == 1
            assert result["rejected_noise"] == 1

            # Check database table
            with db.session() as conn:
                rows = conn.execute("SELECT conversation_id, is_retrieval_friction FROM conversation_qualifications").fetchall()
                assert len(rows) == 2
                res_dict = {r[0]: bool(r[1]) for r in rows}
                assert res_dict["conv_01"] is True
                assert res_dict["conv_02"] is False
