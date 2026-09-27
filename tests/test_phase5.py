import pytest
from pathlib import Path
from unittest.mock import patch

from backend.app.pipeline.scoring import (
    OpportunityScoringManager,
    scoring_manager
)
from backend.app.core.database import DatabaseManager

def test_opportunity_score_math_bounds():
    """Verify opportunity score calculation bounds and component weighting."""
    manager = OpportunityScoringManager()

    # Max inputs: 10/10 volume, 10/10 fails, 5.0/5.0 severity, 3/3 platforms
    score_max, tier_max = manager.compute_score(
        evidence_count=10,
        max_volume=10,
        failed_count=10,
        avg_severity=5.0,
        cluster_platforms=3,
        total_platforms=3
    )
    assert score_max == 1.0
    assert tier_max == "CRITICAL"

    # Zero inputs: 0 volume, 0 fails, 0 severity, 0 platforms
    score_min, tier_min = manager.compute_score(
        evidence_count=0,
        max_volume=10,
        failed_count=0,
        avg_severity=0.0,
        cluster_platforms=0,
        total_platforms=3
    )
    # Small sample Laplace smoothing on 0 gives (0+1)/(0+2) = 0.5 failure rate * 0.3 = 0.15
    assert 0.0 <= score_min <= 0.2
    assert tier_min == "LOW"

def test_bayesian_smoothing_on_small_samples():
    """
    Verify Laplace Bayesian smoothing on small sample sizes (V < 3)
    to prevent small clusters with 1 item from distorting rankings with 100% failure rate.
    """
    manager = OpportunityScoringManager()

    # Sample size 1 with 1 failure -> smoothed rate = (1+1)/(1+2) = 2/3 = 0.667
    score_small, _ = manager.compute_score(
        evidence_count=1,
        max_volume=10,
        failed_count=1,
        avg_severity=5.0,
        cluster_platforms=1,
        total_platforms=3
    )

    # Sample size 3 with 3 failures -> empirical rate = 3/3 = 1.0
    score_large, _ = manager.compute_score(
        evidence_count=3,
        max_volume=10,
        failed_count=3,
        avg_severity=5.0,
        cluster_platforms=1,
        total_platforms=3
    )

    # The large sample must have a higher score due to unconstrained empirical 100% failure rate vs smoothed 66.7%
    assert score_large > score_small

def test_priority_tier_thresholds():
    """Verify priority tier classification against defined thresholds."""
    manager = OpportunityScoringManager()

    # CRITICAL >= 0.75
    s_crit, t_crit = manager.compute_score(10, 10, 10, 4.8, 3, 3)
    assert s_crit >= 0.75
    assert t_crit == "CRITICAL"

    # HIGH 0.55 - 0.74
    s_high, t_high = manager.compute_score(6, 10, 5, 4.0, 2, 3)
    assert 0.55 <= s_high < 0.75
    assert t_high == "HIGH"

    # MEDIUM 0.40 - 0.54
    s_med, t_med = manager.compute_score(4, 10, 2, 3.0, 1, 3)
    assert 0.40 <= s_med < 0.55
    assert t_med == "MEDIUM"

    # LOW < 0.40
    s_low, t_low = manager.compute_score(1, 10, 0, 1.5, 1, 3)
    assert s_low < 0.40
    assert t_low == "LOW"

def test_traceability_graph_integrity(tmp_path):
    """
    Verify complete bidirectional Evidence Traceability Graph generation
    linking a cluster to verified verbatim primary source quotes and extracted signals.
    """
    test_db = tmp_path / "test_traceability.db"
    db = DatabaseManager(db_path=test_db)
    db.init_db()

    with db.session() as conn:
        conn.execute(
            """
            INSERT INTO raw_conversations (id, source, platform, post_date, raw_text, author_pseudonym)
            VALUES ('conv_001', 'play_store', 'android', '2024-03-01', 'Looking for prescription from last winter', 'usr_alpha')
            """
        )
        conn.execute(
            """
            INSERT INTO extracted_signals (id, conversation_id, entities_remembered, spatial_cues, temporal_cues, visual_cues, text_cues, actions_taken, terminal_outcome, frustration_severity, primary_failure_mode)
            VALUES ('sig_001', 'conv_001', '["prescription"]', 'pharmacy', 'last winter', 'blue paper', 'Rx 500mg', '["keyword search"]', 'FAILED_IRRELEVANT', 5, 'Utility Document')
            """
        )
        conn.execute(
            """
            INSERT INTO problem_clusters (id, cluster_name, archetype, root_cause, symptom_description, evidence_count, unique_users_count, failure_rate, average_severity, opportunity_score, opportunity_tier)
            VALUES ('cls_test', 'Utility Document Gap', 'Utility / Document Retrieval Gap', 'No OCR', 'Cannot find Rx', 1, 1, 1.0, 5.0, 0.85, 'CRITICAL')
            """
        )
        conn.execute(
            """
            INSERT INTO signal_cluster_mapping (signal_id, cluster_id, distance_to_centroid)
            VALUES ('sig_001', 'cls_test', 0.12)
            """
        )

    with patch("backend.app.pipeline.scoring.db_manager", db):
        traceability = scoring_manager.get_traceability_graph("cls_test")
        assert traceability is not None
        assert traceability["cluster"]["id"] == "cls_test"
        assert traceability["total_evidence_count"] == 1
        
        ev = traceability["verbatim_evidence"][0]
        assert ev["conversation_id"] == "conv_001"
        assert ev["raw_text"] == "Looking for prescription from last winter"
        assert ev["author_pseudonym"] == "usr_alpha"
        assert ev["source"] == "play_store"
        assert ev["platform"] == "android"
        assert ev["post_date"] == "2024-03-01"
        assert ev["entities_remembered"] == ["prescription"]
        assert ev["distance_to_centroid"] == 0.12

def test_cognitive_journey_graph(tmp_path):
    """Verify node-link journey graph generation mapping memory -> action -> failure -> opportunity."""
    test_db = tmp_path / "test_journey.db"
    db = DatabaseManager(db_path=test_db)
    db.init_db()

    with db.session() as conn:
        conn.execute(
            """
            INSERT INTO raw_conversations (id, source, platform, post_date, raw_text, author_pseudonym)
            VALUES ('conv_001', 'play_store', 'android', '2024-03-01', 'Lost wifi password photo', 'usr_01')
            """
        )
        conn.execute(
            """
            INSERT INTO extracted_signals (id, conversation_id, entities_remembered, spatial_cues, temporal_cues, visual_cues, text_cues, actions_taken, terminal_outcome, frustration_severity, primary_failure_mode)
            VALUES ('sig_001', 'conv_001', '["wifi router"]', 'living room', '', '', '', '["scrolled grid"]', 'FAILED_ZERO_RESULTS', 4, 'Utility Document')
            """
        )
        conn.execute(
            """
            INSERT INTO problem_clusters (id, cluster_name, archetype, root_cause, symptom_description, evidence_count, unique_users_count, failure_rate, average_severity, opportunity_score, opportunity_tier)
            VALUES ('cls_01', 'Utility Document Retrieval Gap', 'Utility / Document Retrieval Gap', 'No OCR', 'Lost wifi', 1, 1, 1.0, 4.0, 0.78, 'CRITICAL')
            """
        )
        conn.execute(
            """
            INSERT INTO signal_cluster_mapping (signal_id, cluster_id, distance_to_centroid)
            VALUES ('sig_001', 'cls_01', 0.1)
            """
        )

    with patch("backend.app.pipeline.scoring.db_manager", db):
        graph = scoring_manager.get_cognitive_journey_graph()
        assert "nodes" in graph
        assert "links" in graph
        assert len(graph["nodes"]) >= 4
        assert len(graph["links"]) >= 3
        categories = set(n["category"] for n in graph["nodes"])
        assert "Memory Anchor" in categories
        assert "Retrieval Action" in categories
        assert "Failure Mode" in categories
        assert "Opportunity Area" in categories

def test_scoring_pipeline_live_update(tmp_path):
    """Verify end-to-end execution of run_scoring_pipeline updates problem_clusters."""
    test_db = tmp_path / "test_scoring_e2e.db"
    db = DatabaseManager(db_path=test_db)
    db.init_db()

    with db.session() as conn:
        conn.execute(
            """
            INSERT INTO raw_conversations (id, source, platform, post_date, raw_text, author_pseudonym)
            VALUES ('c1', 'play_store', 'android', '2024-01-01', 'Query 1', 'u1'),
                   ('c2', 'app_store', 'ios', '2024-01-02', 'Query 2', 'u2'),
                   ('c3', 'reddit', 'web', '2024-01-03', 'Query 3', 'u3')
            """
        )
        conn.execute(
            """
            INSERT INTO extracted_signals (id, conversation_id, terminal_outcome, frustration_severity, primary_failure_mode)
            VALUES ('s1', 'c1', 'FAILED_ZERO_RESULTS', 5, 'Mode A'),
                   ('s2', 'c2', 'FAILED_IRRELEVANT', 4, 'Mode A'),
                   ('s3', 'c3', 'FAILED_ZERO_RESULTS', 5, 'Mode A')
            """
        )
        conn.execute(
            """
            INSERT INTO problem_clusters (id, cluster_name, archetype, root_cause, symptom_description, evidence_count, unique_users_count, failure_rate, average_severity, opportunity_score, opportunity_tier)
            VALUES ('cls_top', 'Top Problem', 'Archetype A', 'Root Cause A', 'Symptom A', 3, 3, 0.0, 0.0, 0.0, 'LOW')
            """
        )
        conn.execute(
            """
            INSERT INTO signal_cluster_mapping (signal_id, cluster_id, distance_to_centroid)
            VALUES ('s1', 'cls_top', 0.1), ('s2', 'cls_top', 0.15), ('s3', 'cls_top', 0.2)
            """
        )

    with patch("backend.app.pipeline.scoring.db_manager", db):
        res = scoring_manager.run_scoring_pipeline()
        assert res["status"] == "success"
        assert res["scored_clusters"] == 1

        with db.session() as conn:
            updated = conn.execute("SELECT opportunity_score, opportunity_tier, failure_rate, average_severity FROM problem_clusters WHERE id = 'cls_top'").fetchone()
            assert updated["opportunity_score"] >= 0.75
            assert updated["opportunity_tier"] == "CRITICAL"
            assert updated["failure_rate"] == 1.0
            assert updated["average_severity"] == 4.67
