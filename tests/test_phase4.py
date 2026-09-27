import pytest
import numpy as np
from pathlib import Path
from unittest.mock import patch

from backend.app.pipeline.clustering import (
    SemanticClusteringManager,
    clustering_manager
)
from backend.app.core.database import DatabaseManager

def test_embedding_generation():
    """Verify 768-d vector embedding generation and caching."""
    manager = SemanticClusteringManager()
    emb = manager.generate_embedding("Looking for doctor prescription from last winter")
    assert isinstance(emb, np.ndarray)
    assert emb.shape == (768,)
    assert np.linalg.norm(emb) > 0.0

def test_hierarchical_clustering_grouping():
    """Verify semantic clustering partitions signals into logical groups."""
    manager = SemanticClusteringManager()
    mock_signals = [
        {"id": "sig_1", "entities_remembered": "prescription", "primary_failure_mode": "Utility Document", "raw_text": "prescription paper"},
        {"id": "sig_2", "entities_remembered": "medicine receipt", "primary_failure_mode": "Utility Document", "raw_text": "medicine receipt"},
        {"id": "sig_3", "entities_remembered": "router wifi password", "primary_failure_mode": "Utility Document", "raw_text": "wifi sticker on router"},
        {"id": "sig_4", "entities_remembered": "cafe neon Paris", "primary_failure_mode": "Unknown Location", "raw_text": "cafe in Paris"},
        {"id": "sig_5", "entities_remembered": "cliff beach Goa", "primary_failure_mode": "Unknown Location", "raw_text": "cliffside lookout Goa"},
    ]
    clusters = manager.cluster_signals(mock_signals, target_distance_threshold=0.8)
    assert len(clusters) >= 1
    total_assigned = sum(len(m) for m in clusters.values())
    assert total_assigned == 5

def test_super_cluster_splitting():
    """
    Edge Case 5.2:
    Verify that if a super-cluster contains > 45% of points, it is partitioned.
    """
    manager = SemanticClusteringManager()
    # 10 identical signals that would naturally fall into 1 single cluster
    mock_signals = [
        {"id": f"sig_{i}", "entities_remembered": "dog", "primary_failure_mode": "Broad Search", "raw_text": f"dog photo {i}"}
        for i in range(10)
    ]
    clusters = manager.cluster_signals(mock_signals, target_distance_threshold=0.9)
    # Because 10/10 = 100% > 45%, the super-cluster splitting logic should partition it
    assert len(clusters) >= 2

def test_clustering_pipeline_end_to_end(tmp_path):
    """
    Verify full clustering pipeline:
      1. Populates mock extracted_signals and raw_conversations in DB.
      2. Runs run_clustering_pipeline().
      3. Verifies problem_clusters and signal_cluster_mapping tables populated.
    """
    test_db = tmp_path / "test_cluster_e2e.db"
    db = DatabaseManager(db_path=test_db)
    db.init_db()

    with db.session() as conn:
        conn.execute(
            """
            INSERT INTO raw_conversations (id, source, post_date, platform, raw_text, author_pseudonym)
            VALUES ('conv_1', 'play_store', '2024-03-01', 'android', 'Prescription search failure', 'usr_01'),
                   ('conv_2', 'app_store', '2024-03-02', 'ios', 'WiFi router sticker lost', 'usr_02')
            """
        )
        conn.execute(
            """
            INSERT INTO extracted_signals (id, conversation_id, entities_remembered, terminal_outcome, frustration_severity, primary_failure_mode)
            VALUES ('sig_1', 'conv_1', '["prescription"]', 'FAILED_IRRELEVANT', 5, 'Utility Document'),
                   ('sig_2', 'conv_2', '["router"]', 'FAILED_ZERO_RESULTS', 4, 'Utility Document')
            """
        )

    mock_profile = {
        "cluster_name": "Utility Document & Voucher Retrieval Gap",
        "archetype": "Utility / Document Retrieval Gap",
        "root_cause": "Absence of OCR text indexing on camera photos",
        "symptom_description": "User unable to find utility photos like prescription or wifi passwords"
    }

    with patch("backend.app.pipeline.clustering.db_manager", db):
        with patch.object(clustering_manager, "synthesize_cluster_profile", return_value=mock_profile):
            result = clustering_manager.run_clustering_pipeline()
            assert result["status"] == "success"
            assert result["clusters_created"] >= 1

            with db.session() as conn:
                clusters = conn.execute("SELECT * FROM problem_clusters").fetchall()
                assert len(clusters) >= 1
                assert clusters[0]["cluster_name"] == "Utility Document & Voucher Retrieval Gap"
                assert clusters[0]["archetype"] == "Utility / Document Retrieval Gap"

                mappings = conn.execute("SELECT * FROM signal_cluster_mapping").fetchall()
                assert len(mappings) == 2
