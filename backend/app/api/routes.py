from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, Optional
from pydantic import BaseModel
from backend.app.services.orchestrator import orchestrator
from backend.app.core.database import db_manager
from backend.app.models.schemas import OverviewMetrics, RelevanceGateOutput, CognitiveExtractionPayload
from backend.app.pipeline.scoring import scoring_manager
from backend.app.pipeline.insights import insight_manager
from backend.app.services.qa_engine import qa_engine

router = APIRouter()

class TextInput(BaseModel):
    text: str
    conversation_id: Optional[str] = "test_conv_001"

class IngestionRequest(BaseModel):
    sources: Optional[list[str]] = None
    limit_per_source: int = 15
    use_fixtures: bool = False

@router.get("/health")
def health_check() -> Dict[str, Any]:
    """Basic health check verifying database and service integrity."""
    db_ok = False
    try:
        with db_manager.session() as conn:
            cursor = conn.execute("SELECT 1")
            db_ok = cursor.fetchone()[0] == 1
    except Exception:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "error",
        "llm_orchestrator": orchestrator.get_status()
    }

@router.post("/ingest/run")
def trigger_ingestion(req: IngestionRequest) -> Dict[str, Any]:
    """
    Triggers multi-platform ingestion, PII scrubbing, Ollama normalization,
    and deduplicated SQLite storage.
    """
    from backend.app.pipeline.ingestion import ingestion_manager
    result = ingestion_manager.run_ingestion(
        sources=req.sources,
        limit_per_source=req.limit_per_source,
        use_fixtures=req.use_fixtures
    )
    return {
        "status": "success",
        "details": result
    }

@router.get("/ingest/status")
def get_ingestion_status() -> Dict[str, Any]:
    """Returns stored conversation counts grouped by source and platform."""
    with db_manager.session() as conn:
        total = conn.execute("SELECT COUNT(*) FROM raw_conversations").fetchone()[0]
        by_source = {
            r[0]: r[1] for r in conn.execute(
                "SELECT source, COUNT(*) FROM raw_conversations GROUP BY source"
            ).fetchall()
        }
        by_platform = {
            r[0]: r[1] for r in conn.execute(
                "SELECT platform, COUNT(*) FROM raw_conversations GROUP BY platform"
            ).fetchall()
        }
        checkpoints = {
            r[0]: {"last_page": r[1], "last_id": r[2]} for r in conn.execute(
                "SELECT source, last_page, last_processed_id FROM ingestion_checkpoints"
            ).fetchall()
        }
        return {
            "total_conversations": total,
            "by_source": by_source,
            "by_platform": by_platform,
            "checkpoints": checkpoints
        }

class QualifyRequest(BaseModel):
    limit: Optional[int] = None

@router.post("/qualify/run")
def trigger_qualification(req: QualifyRequest) -> Dict[str, Any]:
    """
    Runs Layer 1 (Heuristic) and Layer 2 (Local Ollama Intent Classifier)
    across unclassified conversations.
    """
    from backend.app.pipeline.relevance import relevance_manager
    result = relevance_manager.run_qualification_batch(limit=req.limit)
    return {
        "status": "success",
        "details": result
    }

@router.get("/qualify/status")
def get_qualification_status() -> Dict[str, Any]:
    """Returns count and percentage of qualified retrieval friction vs rejected noise."""
    with db_manager.session() as conn:
        total_convs = conn.execute("SELECT COUNT(*) FROM raw_conversations").fetchone()[0]
        total_qualified = conn.execute("SELECT COUNT(*) FROM conversation_qualifications").fetchone()[0]
        friction_count = conn.execute(
            "SELECT COUNT(*) FROM conversation_qualifications WHERE is_retrieval_friction = 1"
        ).fetchone()[0]
        noise_count = conn.execute(
            "SELECT COUNT(*) FROM conversation_qualifications WHERE is_retrieval_friction = 0"
        ).fetchone()[0]

        reasons = [
            {"reason": r[0], "count": r[1]} for r in conn.execute(
                "SELECT filter_reason, COUNT(*) FROM conversation_qualifications GROUP BY filter_reason ORDER BY COUNT(*) DESC LIMIT 5"
            ).fetchall()
        ]

        return {
            "total_conversations": total_convs,
            "total_classified": total_qualified,
            "unclassified": total_convs - total_qualified,
            "qualified_retrieval_friction": friction_count,
            "rejected_noise": noise_count,
            "friction_rate": round(friction_count / total_qualified, 2) if total_qualified > 0 else 0.0,
            "top_filter_reasons": reasons
        }

@router.get("/qualify/records")
def get_qualified_records(limit: int = 50, friction_only: bool = True) -> list[Dict[str, Any]]:
    """Returns qualified conversation items with their qualification rationale and source metadata."""
    with db_manager.session() as conn:
        query = """
            SELECT r.id, r.source, r.platform, r.author_pseudonym, r.raw_text, r.normalized_text,
                   q.is_retrieval_friction, q.confidence_score, q.filter_reason, q.qualified_by
            FROM raw_conversations r
            JOIN conversation_qualifications q ON r.id = q.conversation_id
        """
        if friction_only:
            query += " WHERE q.is_retrieval_friction = 1"
        query += f" ORDER BY q.qualified_at DESC LIMIT {limit}"

        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]

class ExtractRequest(BaseModel):
    limit: Optional[int] = None

@router.post("/extract/run")
def trigger_extraction(req: ExtractRequest) -> Dict[str, Any]:
    """
    Extracts 4-dimensional cognitive memory signals from qualified conversations
    using Gemini Free Tier (with Ollama failover and SQLite caching).
    """
    from backend.app.pipeline.extraction import extraction_manager
    result = extraction_manager.run_extraction_batch(limit=req.limit)
    return {
        "status": "success",
        "details": result
    }

@router.get("/extract/status")
def get_extraction_status() -> Dict[str, Any]:
    """Returns overview of extracted cognitive signals, outcome breakdown, and failure modes."""
    with db_manager.session() as conn:
        total_signals = conn.execute("SELECT COUNT(*) FROM extracted_signals").fetchone()[0]
        outcomes = {
            r[0]: r[1] for r in conn.execute(
                "SELECT terminal_outcome, COUNT(*) FROM extracted_signals GROUP BY terminal_outcome"
            ).fetchall()
        }
        failure_modes = [
            {"mode": r[0], "count": r[1]} for r in conn.execute(
                "SELECT primary_failure_mode, COUNT(*) FROM extracted_signals GROUP BY primary_failure_mode ORDER BY COUNT(*) DESC LIMIT 5"
            ).fetchall()
        ]
        avg_sev = conn.execute("SELECT AVG(frustration_severity) FROM extracted_signals").fetchone()[0] or 0.0

        return {
            "total_extracted_signals": total_signals,
            "outcome_distribution": outcomes,
            "average_frustration_severity": round(float(avg_sev), 2),
            "top_failure_modes": failure_modes
        }

@router.get("/extract/signals")
def get_extracted_signals(limit: int = 50) -> list[Dict[str, Any]]:
    """Returns paginated list of structured cognitive memory signals."""
    import json
    with db_manager.session() as conn:
        query = """
            SELECT s.*, r.raw_text, r.source, r.platform, r.author_pseudonym
            FROM extracted_signals s
            JOIN raw_conversations r ON s.conversation_id = r.id
            ORDER BY s.frustration_severity DESC LIMIT ?
        """
        rows = conn.execute(query, (limit,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["entities_remembered"] = json.loads(d["entities_remembered"])
            except Exception:
                d["entities_remembered"] = []
            try:
                d["actions_taken"] = json.loads(d["actions_taken"])
            except Exception:
                d["actions_taken"] = []
            result.append(d)
        return result

@router.post("/cluster/run")
def trigger_clustering() -> Dict[str, Any]:
    """
    Runs semantic embedding, distance-based hierarchical clustering,
    and cluster profile synthesis across extracted signals.
    """
    from backend.app.pipeline.clustering import clustering_manager
    result = clustering_manager.run_clustering_pipeline()
    return {
        "status": "success",
        "details": result
    }

@router.get("/cluster/list")
def get_clusters_list() -> list[Dict[str, Any]]:
    """Returns all discovered problem clusters with metrics and taxonomy profiles."""
    with db_manager.session() as conn:
        rows = conn.execute("SELECT * FROM problem_clusters ORDER BY evidence_count DESC").fetchall()
        return [dict(r) for r in rows]

@router.get("/cluster/{cluster_id}/signals")
def get_cluster_signals(cluster_id: str) -> list[Dict[str, Any]]:
    """Returns member cognitive memory signals and verbatim quotes mapped to a specific cluster."""
    import json
    with db_manager.session() as conn:
        query = """
            SELECT s.*, r.raw_text, r.source, r.platform, r.author_pseudonym, m.distance_to_centroid
            FROM signal_cluster_mapping m
            JOIN extracted_signals s ON m.signal_id = s.id
            JOIN raw_conversations r ON s.conversation_id = r.id
            WHERE m.cluster_id = ?
            ORDER BY m.distance_to_centroid ASC
        """
        rows = conn.execute(query, (cluster_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["entities_remembered"] = json.loads(d["entities_remembered"])
            except Exception:
                d["entities_remembered"] = []
            try:
                d["actions_taken"] = json.loads(d["actions_taken"])
            except Exception:
                d["actions_taken"] = []
            result.append(d)
        return result

# ==================== Phase 5: Opportunity Scoring & Traceability ====================

@router.post("/score/run")
def trigger_opportunity_scoring() -> Dict[str, Any]:
    """
    Executes multi-criteria opportunity scoring across all problem clusters:
      Score = (V / V_max * 0.35) + (R_fail * 0.30) + (S_avg / 5.0 * 0.20) + (P_cross / P_total * 0.15)
    and classifies clusters into CRITICAL, HIGH, MEDIUM, LOW priority tiers.
    """
    from backend.app.pipeline.scoring import scoring_manager
    return scoring_manager.run_scoring_pipeline()

@router.get("/score/matrix")
def get_opportunity_matrix() -> list[Dict[str, Any]]:
    """
    Returns data formatted for the interactive Opportunity Matrix:
    X: failure_rate, Y: evidence_count, Size: average_severity, Color: opportunity_tier.
    """
    with db_manager.session() as conn:
        rows = conn.execute(
            """
            SELECT id, cluster_name, archetype, evidence_count, unique_users_count,
                   failure_rate, average_severity, opportunity_score, opportunity_tier
            FROM problem_clusters
            ORDER BY opportunity_score DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

@router.get("/problems")
def get_problems(tier: Optional[str] = None, platform: Optional[str] = None) -> list[Dict[str, Any]]:
    """Returns ranked list of problem clusters with optional priority tier and platform filtering."""
    with db_manager.session() as conn:
        if platform:
            query = """
                SELECT DISTINCT c.*
                FROM problem_clusters c
                JOIN signal_cluster_mapping m ON c.id = m.cluster_id
                JOIN extracted_signals s ON m.signal_id = s.id
                JOIN raw_conversations r ON s.conversation_id = r.id
                WHERE LOWER(r.platform) = LOWER(?)
            """
            params = [platform]
            if tier:
                query += " AND UPPER(c.opportunity_tier) = UPPER(?)"
                params.append(tier)
            query += " ORDER BY c.opportunity_score DESC"
            rows = conn.execute(query, params).fetchall()
        elif tier:
            rows = conn.execute(
                "SELECT * FROM problem_clusters WHERE UPPER(opportunity_tier) = UPPER(?) ORDER BY opportunity_score DESC",
                (tier,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM problem_clusters ORDER BY opportunity_score DESC"
            ).fetchall()
        return [dict(r) for r in rows]

@router.get("/problems/compare")
def get_problems_comparison() -> list[Dict[str, Any]]:
    """Returns side-by-side comparison data across all themes/clusters including cues, strategies, platforms, and outcomes."""
    import json
    with db_manager.session() as conn:
        clusters = conn.execute("SELECT * FROM problem_clusters ORDER BY opportunity_score DESC").fetchall()
        comparison = []
        for cl in clusters:
            cid = cl["id"]
            insight_row = conn.execute("SELECT * FROM product_insights WHERE cluster_id = ?", (cid,)).fetchone()
            insight = dict(insight_row) if insight_row else {}

            signals_rows = conn.execute("""
                SELECT s.*, r.raw_text, r.source, r.platform, r.author_pseudonym, r.source_url
                FROM signal_cluster_mapping m
                JOIN extracted_signals s ON m.signal_id = s.id
                JOIN raw_conversations r ON s.conversation_id = r.id
                WHERE m.cluster_id = ?
            """, (cid,)).fetchall()

            cues_count: Dict[str, int] = {}
            strategies_count: Dict[str, int] = {}
            outcomes_count: Dict[str, int] = {}
            platforms_count: Dict[str, int] = {}
            evidence_list = []

            for sr in signals_rows:
                # Platforms
                p = sr["platform"] or "unknown"
                platforms_count[p] = platforms_count.get(p, 0) + 1

                # Outcomes
                oc = sr["terminal_outcome"] or "ABANDONED"
                outcomes_count[oc] = outcomes_count.get(oc, 0) + 1

                # Strategies from actions_taken
                try:
                    acts = json.loads(sr["actions_taken"]) if sr["actions_taken"] else []
                except Exception:
                    acts = []
                for act in acts:
                    atype = act.get("action_type", "text_query") if isinstance(act, dict) else "text_query"
                    strategies_count[atype] = strategies_count.get(atype, 0) + 1
                if not acts:
                    strategies_count["text_query"] = strategies_count.get("text_query", 0) + 1

                # Cue types
                if sr["text_cues"]:
                    cues_count["Embedded Text"] = cues_count.get("Embedded Text", 0) + 1
                if sr["visual_cues"]:
                    cues_count["Visual/Aesthetic"] = cues_count.get("Visual/Aesthetic", 0) + 1
                if sr["temporal_cues"]:
                    cues_count["Temporal"] = cues_count.get("Temporal", 0) + 1
                if sr["spatial_cues"]:
                    cues_count["Spatial"] = cues_count.get("Spatial", 0) + 1
                try:
                    ents = json.loads(sr["entities_remembered"]) if sr["entities_remembered"] else []
                except Exception:
                    ents = []
                if ents:
                    cues_count["Entities/People"] = cues_count.get("Entities/People", 0) + 1

                evidence_list.append({
                    "id": sr["id"],
                    "conversation_id": sr["conversation_id"],
                    "raw_text": sr["raw_text"],
                    "source": sr["source"],
                    "platform": sr["platform"],
                    "author": sr["author_pseudonym"],
                    "source_url": sr["source_url"],
                    "severity": sr["frustration_severity"],
                    "outcome": sr["terminal_outcome"],
                    "entities": ents
                })

            comparison.append({
                "id": cl["id"],
                "cluster_name": cl["cluster_name"],
                "archetype": cl["archetype"],
                "evidence_count": cl["evidence_count"],
                "failure_rate": cl["failure_rate"],
                "average_severity": cl["average_severity"],
                "opportunity_score": cl["opportunity_score"],
                "opportunity_tier": cl["opportunity_tier"],
                "root_cause": cl["root_cause"],
                "symptom_description": cl["symptom_description"],
                "recommended_feature": insight.get("recommended_feature_direction", ""),
                "opportunity_statement": insight.get("opportunity_statement", ""),
                "platforms": platforms_count,
                "cue_types": cues_count,
                "query_strategies": strategies_count,
                "outcomes": outcomes_count,
                "representative_quote": evidence_list[0] if evidence_list else None,
                "evidence_count_actual": len(evidence_list)
            })

        return comparison

@router.get("/problems/{cluster_id}")
def get_problem_detail(cluster_id: str) -> Dict[str, Any]:
    """Returns detailed problem cluster profile and associated synthesized insights."""
    with db_manager.session() as conn:
        row = conn.execute("SELECT * FROM problem_clusters WHERE id = ?", (cluster_id,)).fetchone()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Problem cluster not found")
        data = dict(row)
        insight = conn.execute("SELECT * FROM product_insights WHERE cluster_id = ?", (cluster_id,)).fetchone()
        data["product_insight"] = dict(insight) if insight else None
        return data

@router.get("/problems/{cluster_id}/traceability")
def get_cluster_traceability(cluster_id: str) -> Dict[str, Any]:
    """
    Returns the complete bidirectional Evidence Traceability Graph linking the cluster
    directly to primary user quotes, extracted memory cues, and source metadata.
    """
    from backend.app.pipeline.scoring import scoring_manager
    graph = scoring_manager.get_traceability_graph(cluster_id)
    if not graph:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Problem cluster not found")
    return graph

@router.get("/problems/{cluster_id}/evidence")
def get_cluster_evidence(cluster_id: str, platform: Optional[str] = None, limit: int = 50) -> list[Dict[str, Any]]:
    """Returns paginated verbatim evidence quotes with verified source metadata and optional platform filter."""
    from backend.app.pipeline.scoring import scoring_manager
    graph = scoring_manager.get_traceability_graph(cluster_id)
    if not graph:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Problem cluster not found")
    evidence = graph.get("verbatim_evidence", [])
    if platform:
        evidence = [e for e in evidence if str(e.get("platform", "")).lower() == platform.lower()]
    return evidence[:limit]

@router.get("/journey/graph")
def get_journey_graph() -> Dict[str, Any]:
    """
    Returns the 4-stage Cognitive Retrieval Journey flow:
    Memory Anchors -> Actions Attempted -> Failure Modes -> Opportunity Areas
    for interactive Sankey/Flow visualization.
    """
    from backend.app.pipeline.scoring import scoring_manager
    return scoring_manager.get_cognitive_journey_graph()

# ==================== Phase 6: Product Discovery Insight Cards & 10-Question Report ====================

@router.post("/insights/generate")
def trigger_insights_generation() -> Dict[str, Any]:
    """
    Synthesizes 4-part Product Discovery Cards across all problem clusters
    using Gemini Free Tier / local Ollama and persists to product_insights table.
    """
    from backend.app.pipeline.insights import insight_manager
    return insight_manager.generate_all_discovery_cards()

@router.get("/insights/cards")
def get_all_discovery_cards() -> list[Dict[str, Any]]:
    """
    Returns all synthesized 4-part Product Discovery Cards:
    User Memory Pattern -> Retrieval Pattern -> Failure Pattern -> Product Opportunity Statement.
    """
    from backend.app.pipeline.insights import insight_manager
    return insight_manager.get_discovery_cards()

@router.get("/insights/cards/{cluster_id}")
def get_discovery_card(cluster_id: str) -> Dict[str, Any]:
    """Returns the synthesized Product Discovery Card for a specific cluster."""
    with db_manager.session() as conn:
        row = conn.execute(
            """
            SELECT i.*, c.cluster_name, c.archetype, c.root_cause, c.opportunity_score, c.opportunity_tier
            FROM product_insights i
            JOIN problem_clusters c ON i.cluster_id = c.id
            WHERE i.cluster_id = ?
            """,
            (cluster_id,)
        ).fetchone()
        if not row:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Discovery card not found for this cluster")
        return dict(row)

@router.get("/report/discovery-brief")
def get_discovery_report() -> Dict[str, Any]:
    """
    Returns the comprehensive 10-Question PM Discovery Report
    grounded in empirical statistics and verbatim citations from SQLite.
    """
    from backend.app.pipeline.insights import insight_manager
    return insight_manager.generate_10_question_report()



@router.get("/llm/status")
def get_llm_status() -> Dict[str, Any]:
    """Returns real-time status of Gemini rate limits, Ollama local daemon, and disk cache."""
    return orchestrator.get_status()

@router.get("/metrics/overview", response_model=OverviewMetrics)
def get_overview_metrics(platform: Optional[str] = None):
    """Returns global or platform-specific dataset and cognitive friction summary metrics."""
    with db_manager.session() as conn:
        all_platforms = [r[0] for r in conn.execute("SELECT DISTINCT platform FROM raw_conversations").fetchall()]
        
        if platform:
            total_convs = conn.execute(
                "SELECT COUNT(*) FROM raw_conversations WHERE LOWER(platform) = LOWER(?)", (platform,)
            ).fetchone()[0]
            sources = [
                r[0] for r in conn.execute(
                    "SELECT DISTINCT source FROM raw_conversations WHERE LOWER(platform) = LOWER(?)", (platform,)
                ).fetchall()
            ]
            relevant_count = conn.execute(
                """
                SELECT COUNT(*) FROM conversation_qualifications q
                JOIN raw_conversations r ON q.conversation_id = r.id
                WHERE q.is_retrieval_friction = 1 AND LOWER(r.platform) = LOWER(?)
                """,
                (platform,)
            ).fetchone()[0]

            total_signals = conn.execute(
                """
                SELECT COUNT(*) FROM extracted_signals s
                JOIN raw_conversations r ON s.conversation_id = r.id
                WHERE LOWER(r.platform) = LOWER(?)
                """,
                (platform,)
            ).fetchone()[0]

            failed_count = conn.execute(
                """
                SELECT COUNT(*) FROM extracted_signals s
                JOIN raw_conversations r ON s.conversation_id = r.id
                WHERE s.terminal_outcome IN ('FAILED_ZERO_RESULTS', 'FAILED_IRRELEVANT', 'ABANDONED')
                  AND LOWER(r.platform) = LOWER(?)
                """,
                (platform,)
            ).fetchone()[0]

            avg_sev = conn.execute(
                """
                SELECT AVG(s.frustration_severity) FROM extracted_signals s
                JOIN raw_conversations r ON s.conversation_id = r.id
                WHERE LOWER(r.platform) = LOWER(?)
                """,
                (platform,)
            ).fetchone()[0] or 0.0

            top_arch_row = conn.execute(
                """
                SELECT c.archetype FROM problem_clusters c
                JOIN signal_cluster_mapping m ON c.id = m.cluster_id
                JOIN extracted_signals s ON m.signal_id = s.id
                JOIN raw_conversations r ON s.conversation_id = r.id
                WHERE LOWER(r.platform) = LOWER(?)
                ORDER BY c.opportunity_score DESC LIMIT 1
                """,
                (platform,)
            ).fetchone()
            top_arch_name = top_arch_row[0] if top_arch_row else "Event-Based Retrieval"
            platforms_list = [platform]
        else:
            total_convs = conn.execute("SELECT COUNT(*) FROM raw_conversations").fetchone()[0]
            sources = [r[0] for r in conn.execute("SELECT DISTINCT source FROM raw_conversations").fetchall()]
            relevant_count = conn.execute(
                "SELECT COUNT(*) FROM conversation_qualifications WHERE is_retrieval_friction = 1"
            ).fetchone()[0]

            total_signals = conn.execute("SELECT COUNT(*) FROM extracted_signals").fetchone()[0]
            failed_count = conn.execute(
                "SELECT COUNT(*) FROM extracted_signals WHERE terminal_outcome IN ('FAILED_ZERO_RESULTS', 'FAILED_IRRELEVANT', 'ABANDONED')"
            ).fetchone()[0]

            avg_sev = conn.execute("SELECT AVG(frustration_severity) FROM extracted_signals").fetchone()[0] or 0.0

            top_arch = conn.execute("SELECT archetype FROM problem_clusters ORDER BY opportunity_score DESC LIMIT 1").fetchone()
            top_arch_name = top_arch[0] if top_arch else "Event-Based Retrieval"
            platforms_list = all_platforms or ["Android", "iOS", "Web"]

        failure_rate = (failed_count / total_signals) if total_signals > 0 else 0.0

        return OverviewMetrics(
            total_sources_collected=len(sources),
            total_conversations=total_convs,
            relevant_conversations=relevant_count,
            unique_users=total_convs,
            system_failure_rate=round(failure_rate, 2),
            average_severity=round(float(avg_sev), 2),
            platforms_represented=platforms_list,
            top_opportunity_archetype=top_arch_name
        )

@router.post("/test/normalize")
def test_normalize(input_data: TextInput) -> Dict[str, str]:
    """Test the local Ollama text normalization function."""
    clean_text = orchestrator.normalize_text(input_data.text)
    return {
        "raw_text": input_data.text,
        "normalized_text": clean_text
    }

@router.post("/test/relevance", response_model=RelevanceGateOutput)
def test_relevance(input_data: TextInput):
    """Test the local Ollama zero-shot retrieval friction classifier."""
    return orchestrator.classify_relevance(input_data.text)

@router.post("/test/extract", response_model=CognitiveExtractionPayload)
def test_extract(input_data: TextInput):
    """Test the structured cognitive extraction engine (Gemini with Ollama fallback)."""
    return orchestrator.extract_cognitive_signals(input_data.text, input_data.conversation_id)

class AskQuestionRequest(BaseModel):
    question: str
    limit: Optional[int] = 8

@router.post("/ask")
def ask_question_endpoint(req: AskQuestionRequest) -> Dict[str, Any]:
    """
    Answers a question about user photo search struggles grounded
    strictly in authentic reviews from Google Play, App Store, and Reddit.
    """
    from backend.app.services.qa_engine import qa_engine
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    return qa_engine.answer_question(req.question.strip(), limit=req.limit or 8)

