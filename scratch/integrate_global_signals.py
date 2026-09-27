import sqlite3
import json
import logging
from backend.app.core.database import db_manager
from backend.app.pipeline.extraction import CognitiveSignalExtractor
from backend.app.pipeline.scoring import scoring_manager

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Mapping from failure modes to cluster IDs in problem_clusters
THEME_TO_CLUSTER_ID = {
    "Utility / Document Retrieval Gap": "cls_util_doc",
    "Weak Search Vocabulary": "cls_weak_vocab",
    "Event-Based Multi-Entity Retrieval": "cls_multi_entity",
    "Incomplete Memory": "cls_incomp_mem",
    "Metadata Dependency Trap (Stripped EXIF)": "cls_exif_trap",
    "Visual-Concept Search Gap": "cls_visual_gap",
    "Oversaturation / Low Precision": "cls_visual_gap", # grouped with visual precision gap
    "Unknown Time (Temporal Vagueness)": "cls_unknown_time",
    "Unknown Location (Spatial Vagueness)": "cls_incomp_mem"
}

def integrate_unextracted_signals():
    query = """
        SELECT r.id, r.platform, COALESCE(r.normalized_text, r.raw_text) as text
        FROM raw_conversations r
        JOIN conversation_qualifications q ON r.id = q.conversation_id
        LEFT JOIN extracted_signals s ON r.id = s.conversation_id
        WHERE q.is_retrieval_friction = 1 AND s.conversation_id IS NULL
    """
    with db_manager.session() as conn:
        unextracted = [dict(r) for r in conn.execute(query).fetchall()]

    print(f"Found {len(unextracted)} qualified global retrieval friction records to extract and map...")

    extractor = CognitiveSignalExtractor()
    extracted_rows = []
    mapping_rows = []

    for item in unextracted:
        conv_id = item["id"]
        text = item["text"]
        payload = extractor.heuristic_extract(conv_id, text)
        signal_id = f"sig_{conv_id}"

        extracted_rows.append((
            signal_id,
            conv_id,
            json.dumps(payload.memory_signals.entities_remembered),
            payload.memory_signals.spatial_cues,
            payload.memory_signals.temporal_cues,
            payload.memory_signals.visual_aesthetic_cues,
            payload.memory_signals.embedded_text_cues,
            1 if payload.forgotten_signals.exact_date_forgotten else 0,
            1 if payload.forgotten_signals.exact_location_forgotten else 0,
            1 if payload.forgotten_signals.filename_forgotten else 0,
            json.dumps([a.model_dump() for a in payload.actions_taken]),
            payload.outcome.value,
            payload.user_frustration_level,
            payload.primary_failure_mode,
            "global_heuristic_extractor"
        ))

        cluster_id = THEME_TO_CLUSTER_ID.get(payload.primary_failure_mode, "cls_incomp_mem")
        mapping_rows.append((
            signal_id,
            cluster_id,
            0.15
        ))

    with db_manager.session() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO extracted_signals
            (id, conversation_id, entities_remembered, spatial_cues, temporal_cues,
             visual_cues, text_cues, date_forgotten, location_forgotten, filename_forgotten,
             actions_taken, terminal_outcome, frustration_severity, primary_failure_mode, extracted_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            extracted_rows
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO signal_cluster_mapping
            (signal_id, cluster_id, distance_to_centroid)
            VALUES (?, ?, ?)
            """,
            mapping_rows
        )

    print(f"Successfully inserted {len(extracted_rows)} extracted signals and cluster mappings.")

    # Recalculate cluster aggregate metrics (evidence count, volume, failure rate, opportunity scores)
    with db_manager.session() as conn:
        # Update evidence_count, unique_users_count, failure_rate, average_severity for each cluster
        clusters = conn.execute("SELECT id FROM problem_clusters").fetchall()
        for cl in clusters:
            cid = cl["id"]
            stats = conn.execute(
                """
                SELECT 
                    COUNT(s.id) as total_evidence,
                    COUNT(DISTINCT r.author_pseudonym) as unique_users,
                    AVG(s.frustration_severity) as avg_sev,
                    SUM(CASE WHEN s.terminal_outcome IN ('FAILED_ZERO_RESULTS', 'FAILED_IRRELEVANT', 'ABANDONED') THEN 1 ELSE 0 END) as fail_count,
                    COUNT(DISTINCT r.platform) as num_platforms
                FROM signal_cluster_mapping m
                JOIN extracted_signals s ON m.signal_id = s.id
                JOIN raw_conversations r ON s.conversation_id = r.id
                WHERE m.cluster_id = ?
                """,
                (cid,)
            ).fetchone()

            tot_ev = stats["total_evidence"] or 0
            uniq_users = stats["unique_users"] or 0
            avg_sev = round(stats["avg_sev"] or 3.5, 2)
            fail_cnt = stats["fail_count"] or 0
            fail_rate = round(fail_cnt / tot_ev, 3) if tot_ev > 0 else 0.0

            conn.execute(
                """
                UPDATE problem_clusters
                SET evidence_count = ?,
                    unique_users_count = ?,
                    average_severity = ?,
                    failure_rate = ?
                WHERE id = ?
                """,
                (tot_ev, uniq_users, avg_sev, fail_rate, cid)
            )

    # Recalculate Opportunity Scores
    res = scoring_manager.recalculate_all_scores()
    print("Recalculated Opportunity Scores:", res)

if __name__ == "__main__":
    integrate_unextracted_signals()
