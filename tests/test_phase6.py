import pytest
from unittest.mock import patch

from backend.app.pipeline.insights import (
    ProductInsightManager,
    insight_manager
)
from backend.app.core.database import DatabaseManager

def test_discovery_card_synthesis_structure():
    """Verify 4-part Product Discovery Card schema synthesis."""
    manager = ProductInsightManager()
    cluster = {
        "id": "cls_test",
        "cluster_name": "Multi-Person Relational Query Gap",
        "archetype": "Event-Based Multi-Entity Retrieval",
        "root_cause": "Search engine treats multiple query entities as independent filters",
        "symptom_description": "Users search for two people together and receive zero results"
    }
    mock_evidence = [
        {
            "raw_text": "Searched Sarah and Kevin farewell dinner, returned 0 photos",
            "platform": "android",
            "author_pseudonym": "usr_test1",
            "entities_remembered": "Sarah, Kevin",
            "terminal_outcome": "FAILED_ZERO_RESULTS",
            "frustration_severity": 5
        }
    ]

    card = manager.synthesize_discovery_card(cluster, mock_evidence)
    assert "user_memory_pattern" in card
    assert "retrieval_pattern" in card
    assert "failure_pattern" in card
    assert "opportunity_statement" in card
    assert "recommended_feature_direction" in card
    assert len(card["user_memory_pattern"]) > 20
    assert len(card["opportunity_statement"]) > 20

def test_batch_discovery_cards_generation_and_db_persistence(tmp_path):
    """Verify end-to-end card generation and persistence into SQLite product_insights table."""
    test_db = tmp_path / "test_insights_e2e.db"
    db = DatabaseManager(db_path=test_db)
    db.init_db()

    with db.session() as conn:
        conn.execute(
            """
            INSERT INTO raw_conversations (id, source, platform, post_date, raw_text, author_pseudonym)
            VALUES ('c1', 'play_store', 'android', '2024-01-01', 'Looking for medical prescription', 'u1')
            """
        )
        conn.execute(
            """
            INSERT INTO extracted_signals (id, conversation_id, terminal_outcome, frustration_severity, primary_failure_mode)
            VALUES ('s1', 'c1', 'FAILED_ZERO_RESULTS', 5, 'Utility / Document Retrieval Gap')
            """
        )
        conn.execute(
            """
            INSERT INTO problem_clusters (id, cluster_name, archetype, root_cause, symptom_description, evidence_count, unique_users_count, failure_rate, average_severity, opportunity_score, opportunity_tier)
            VALUES ('cls_doc', 'Utility Document Gap', 'Utility / Document Retrieval Gap', 'No OCR', 'Lost prescription', 1, 1, 1.0, 5.0, 0.92, 'CRITICAL')
            """
        )
        conn.execute(
            """
            INSERT INTO signal_cluster_mapping (signal_id, cluster_id, distance_to_centroid)
            VALUES ('s1', 'cls_doc', 0.1)
            """
        )

    with patch("backend.app.pipeline.insights.db_manager", db):
        res = insight_manager.generate_all_discovery_cards()
        assert res["status"] == "success"
        assert res["cards_generated"] == 1

        with db.session() as conn:
            rows = conn.execute("SELECT * FROM product_insights").fetchall()
            assert len(rows) == 1
            assert rows[0]["cluster_id"] == "cls_doc"
            assert "prescription" in rows[0]["user_memory_pattern"].lower() or "utilitarian" in rows[0]["user_memory_pattern"].lower()

        cards = insight_manager.get_discovery_cards()
        assert len(cards) == 1
        assert cards[0]["cluster_id"] == "cls_doc"
        assert cards[0]["opportunity_score"] == 0.92

def test_10_question_report_structure_and_citations(tmp_path):
    """Verify compilation of the 10-Question Strategic PM Discovery Report with citations."""
    test_db = tmp_path / "test_report.db"
    db = DatabaseManager(db_path=test_db)
    db.init_db()

    with db.session() as conn:
        conn.execute(
            """
            INSERT INTO raw_conversations (id, source, platform, post_date, raw_text, author_pseudonym)
            VALUES ('c1', 'play_store', 'android', '2024-01-01', 'Searched Sarah and Kevin, got 0 results', 'u1')
            """
        )
        conn.execute(
            """
            INSERT INTO conversation_qualifications (conversation_id, is_retrieval_friction, confidence_score)
            VALUES ('c1', 1, 0.95)
            """
        )
        conn.execute(
            """
            INSERT INTO extracted_signals (id, conversation_id, terminal_outcome, frustration_severity, primary_failure_mode)
            VALUES ('s1', 'c1', 'FAILED_ZERO_RESULTS', 5, 'Event-Based Multi-Entity Retrieval')
            """
        )
        conn.execute(
            """
            INSERT INTO problem_clusters (id, cluster_name, archetype, root_cause, symptom_description, evidence_count, unique_users_count, failure_rate, average_severity, opportunity_score, opportunity_tier)
            VALUES ('cls_event', 'Multi-Person Relational Query Gap', 'Event-Based Multi-Entity Retrieval', 'Independent filters', '0 results', 1, 1, 1.0, 5.0, 1.0, 'CRITICAL')
            """
        )

    with patch("backend.app.pipeline.insights.db_manager", db):
        report = insight_manager.generate_10_question_report()
        assert "meta" in report
        assert report["meta"]["total_conversations_analyzed"] == 1
        assert report["meta"]["qualified_friction_cases"] == 1
        
        questions = report["questions"]
        assert len(questions) == 10
        for i, q in enumerate(questions, start=1):
            assert q["question_id"] == i
            assert "title" in q
            assert "key_findings" in q
            assert "empirical_evidence" in q
            assert "representative_quote" in q

        md = report["markdown_report"]
        assert "# Google Photos Strategic Product Discovery Report" in md
        for i in range(1, 11):
            assert f"### Q{i}:" in md
