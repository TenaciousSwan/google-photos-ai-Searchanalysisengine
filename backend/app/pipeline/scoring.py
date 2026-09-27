import json
import logging
from typing import Dict, Any, List, Optional, Tuple

from backend.app.core.database import db_manager
from backend.app.models.schemas import PriorityTierEnum

logger = logging.getLogger(__name__)

class OpportunityScoringManager:
    """
    Mathematical Opportunity Scoring Engine & Evidence Traceability Indexer.
    
    Implements:
      1. Multi-criteria opportunity scoring:
         Score = (V / V_max * 0.35) + (R_fail * 0.30) + (S_avg / 5.0 * 0.20) + (P_cross / P_total * 0.15)
      2. Bayesian smoothing for low-volume clusters (V < 3).
      3. Priority tier discretization (CRITICAL >= 0.75, HIGH 0.55-0.74, MEDIUM 0.40-0.54, LOW < 0.40).
      4. Bidirectional Evidence Traceability Graph linking high-level clusters directly to primary quotes.
      5. Cognitive Retrieval Journey Graph generation (Memory Anchor -> Action -> Failure -> Opportunity).
    """

    @staticmethod
    def compute_score(
        evidence_count: int,
        max_volume: int,
        failed_count: int,
        avg_severity: float,
        cluster_platforms: int,
        total_platforms: int
    ) -> Tuple[float, str]:
        """
        Calculates normalized opportunity score [0.0, 1.0] and priority tier.
        Applies Bayesian Laplace smoothing to failure rate if evidence_count < 3.
        """
        # 1. Volume ratio (V / V_max)
        v_norm = (evidence_count / max_volume) if max_volume > 0 else 0.0
        v_norm = min(1.0, max(0.0, v_norm))

        # 2. Failure rate with Bayesian smoothing for small samples
        if evidence_count < 3:
            # Laplace smoothing: (fails + 1) / (total + 2)
            r_fail = (failed_count + 1.0) / (evidence_count + 2.0)
        else:
            r_fail = (failed_count / evidence_count) if evidence_count > 0 else 0.0
        r_fail = min(1.0, max(0.0, r_fail))

        # 3. Severity normalization (S_avg / 5.0)
        s_norm = (avg_severity / 5.0) if avg_severity > 0 else 0.0
        s_norm = min(1.0, max(0.0, s_norm))

        # 4. Cross-platform prevalence (P_cross / P_total)
        p_norm = (cluster_platforms / total_platforms) if total_platforms > 0 else 1.0
        p_norm = min(1.0, max(0.0, p_norm))

        # Formula: 0.35 * V + 0.30 * R_fail + 0.20 * S + 0.15 * P_cross
        raw_score = (v_norm * 0.35) + (r_fail * 0.30) + (s_norm * 0.20) + (p_norm * 0.15)
        score = round(min(1.0, max(0.0, raw_score)), 3)

        # Priority tier assignment
        if score >= 0.75:
            tier = PriorityTierEnum.CRITICAL.value
        elif score >= 0.55:
            tier = PriorityTierEnum.HIGH.value
        elif score >= 0.40:
            tier = PriorityTierEnum.MEDIUM.value
        else:
            tier = PriorityTierEnum.LOW.value

        return score, tier

    def run_scoring_pipeline(self) -> Dict[str, Any]:
        """
        Executes scoring across all clusters in `problem_clusters` table,
        updating opportunity_score and opportunity_tier in SQLite.
        """
        with db_manager.session() as conn:
            # 1. Fetch all clusters
            clusters = [dict(r) for r in conn.execute("SELECT * FROM problem_clusters").fetchall()]
            if not clusters:
                return {"status": "no_clusters_found", "scored_count": 0}

            # 2. Total platforms in dataset
            total_platforms_rows = conn.execute("SELECT DISTINCT platform FROM raw_conversations").fetchall()
            total_platforms = max(1, len(total_platforms_rows))

            # 3. Max volume among clusters
            max_volume = max((c.get("evidence_count", 0) for c in clusters), default=1)

            scored_records = []
            for c in clusters:
                cluster_id = c["id"]

                # Fetch member signals to determine failure count and platform count
                member_query = """
                    SELECT s.terminal_outcome, s.frustration_severity, r.platform
                    FROM signal_cluster_mapping m
                    JOIN extracted_signals s ON m.signal_id = s.id
                    JOIN raw_conversations r ON s.conversation_id = r.id
                    WHERE m.cluster_id = ?
                """
                members = [dict(r) for r in conn.execute(member_query, (cluster_id,)).fetchall()]
                evidence_count = len(members)

                failed_count = sum(
                    1 for m in members if m.get("terminal_outcome") in ("FAILED_ZERO_RESULTS", "FAILED_IRRELEVANT", "ABANDONED")
                )
                severities = [m.get("frustration_severity", 3) for m in members if m.get("frustration_severity")]
                avg_sev = (sum(severities) / len(severities)) if severities else c.get("average_severity", 3.0)

                cluster_platforms = len(set(m.get("platform") for m in members if m.get("platform")))

                score, tier = self.compute_score(
                    evidence_count=evidence_count,
                    max_volume=max_volume,
                    failed_count=failed_count,
                    avg_severity=avg_sev,
                    cluster_platforms=cluster_platforms,
                    total_platforms=total_platforms
                )

                # Update database
                conn.execute(
                    """
                    UPDATE problem_clusters
                    SET opportunity_score = ?, opportunity_tier = ?, evidence_count = ?, failure_rate = ?, average_severity = ?
                    WHERE id = ?
                    """,
                    (
                        score,
                        tier,
                        evidence_count,
                        round(failed_count / evidence_count, 2) if evidence_count > 0 else 0.0,
                        round(avg_sev, 2),
                        cluster_id
                    )
                )

                scored_records.append({
                    "id": cluster_id,
                    "cluster_name": c.get("cluster_name"),
                    "archetype": c.get("archetype"),
                    "score": score,
                    "tier": tier,
                    "evidence_count": evidence_count,
                    "platforms_represented": cluster_platforms
                })

        return {
            "status": "success",
            "scored_clusters": len(scored_records),
            "clusters": scored_records
        }

    def get_traceability_graph(self, cluster_id: str) -> Optional[Dict[str, Any]]:
        """
        Constructs a complete evidence traceability graph linking a cluster directly
        to primary user conversations and granular extracted cognitive cues.
        """
        with db_manager.session() as conn:
            cluster_row = conn.execute("SELECT * FROM problem_clusters WHERE id = ?", (cluster_id,)).fetchone()
            if not cluster_row:
                return None

            cluster = dict(cluster_row)

            # Query all linked signals and raw evidence
            query = """
                SELECT 
                    s.id AS signal_id,
                    s.entities_remembered,
                    s.spatial_cues,
                    s.temporal_cues,
                    s.visual_cues,
                    s.text_cues,
                    s.date_forgotten,
                    s.location_forgotten,
                    s.filename_forgotten,
                    s.actions_taken,
                    s.terminal_outcome,
                    s.frustration_severity,
                    s.primary_failure_mode,
                    r.id AS conversation_id,
                    r.source,
                    r.platform,
                    r.post_date,
                    r.raw_text,
                    r.author_pseudonym,
                    m.distance_to_centroid
                FROM signal_cluster_mapping m
                JOIN extracted_signals s ON m.signal_id = s.id
                JOIN raw_conversations r ON s.conversation_id = r.id
                WHERE m.cluster_id = ?
                ORDER BY m.distance_to_centroid ASC
            """
            rows = conn.execute(query, (cluster_id,)).fetchall()

            evidence_items = []
            for r in rows:
                item = dict(r)
                # Parse JSON arrays safely
                for field in ("entities_remembered", "actions_taken"):
                    if isinstance(item.get(field), str):
                        try:
                            item[field] = json.loads(item[field])
                        except Exception:
                            item[field] = [item[field]] if item[field] else []
                evidence_items.append(item)

            return {
                "cluster": cluster,
                "total_evidence_count": len(evidence_items),
                "verbatim_evidence": evidence_items,
                "traceability_integrity": {
                    "verified_quotes_count": len(evidence_items),
                    "zero_evidence_warning": len(evidence_items) == 0,
                    "cross_platform_sources": list(set(e["source"] for e in evidence_items))
                }
            }

    def get_cognitive_journey_graph(self) -> Dict[str, Any]:
        """
        Synthesizes the 4-stage Cognitive Retrieval Journey flow:
          Memory Anchors -> Actions Attempted -> Failure Modes -> Opportunity Areas
        Suitable for Sankey / Journey visualization in the discovery dashboard.
        """
        with db_manager.session() as conn:
            query = """
                SELECT 
                    s.entities_remembered,
                    s.spatial_cues,
                    s.temporal_cues,
                    s.actions_taken,
                    s.primary_failure_mode,
                    c.cluster_name,
                    c.opportunity_tier,
                    c.opportunity_score
                FROM signal_cluster_mapping m
                JOIN extracted_signals s ON m.signal_id = s.id
                JOIN problem_clusters c ON m.cluster_id = c.id
            """
            rows = conn.execute(query).fetchall()

            nodes = []
            node_indices = {}
            links = []

            def get_or_create_node(name: str, category: str) -> int:
                key = f"{category}::{name}"
                if key not in node_indices:
                    idx = len(nodes)
                    node_indices[key] = idx
                    nodes.append({"id": idx, "name": name, "category": category})
                return node_indices[key]

            for r in rows:
                # Stage 1: Memory Anchor
                anchor = "Episodic Recall"
                if r["spatial_cues"]:
                    anchor = "Spatial / Setting Anchor"
                elif r["temporal_cues"]:
                    anchor = "Relative Time Anchor"
                elif r["entities_remembered"]:
                    anchor = "Entity / Object Recall"

                # Stage 2: Action Attempted
                actions = []
                try:
                    actions = json.loads(r["actions_taken"]) if isinstance(r["actions_taken"], str) else (r["actions_taken"] or [])
                except Exception:
                    actions = ["Keyword Search"]
                
                first_act = actions[0] if actions else "Keyword Search"
                if isinstance(first_act, dict):
                    q_str = first_act.get("query_string")
                    a_type = first_act.get("action_type", "text_query")
                    if q_str:
                        action_str = f'Search: "{q_str}"'
                    elif a_type == "manual_scroll":
                        action_str = "Manual Timeline Scroll"
                    elif a_type == "album_filter":
                        action_str = "Album / Favorites Filter"
                    elif a_type == "date_filter":
                        action_str = "Date Filter Scrubbing"
                    elif a_type == "face_tag":
                        action_str = "People / Face Filter"
                    else:
                        action_str = "Keyword Search"
                elif isinstance(first_act, str):
                    action_str = first_act
                else:
                    action_str = "Keyword Search"

                # Stage 3: Failure Mode
                failure_mode = r["primary_failure_mode"] or "Incomplete Memory"

                # Stage 4: Opportunity Area (Cluster Name)
                opportunity_name = r["cluster_name"]

                idx_anchor = get_or_create_node(anchor, "Memory Anchor")
                idx_action = get_or_create_node(action_str, "Retrieval Action")
                idx_failure = get_or_create_node(failure_mode, "Failure Mode")
                idx_opportunity = get_or_create_node(opportunity_name, "Opportunity Area")

                links.append({"source": idx_anchor, "target": idx_action, "value": 1})
                links.append({"source": idx_action, "target": idx_failure, "value": 1})
                links.append({"source": idx_failure, "target": idx_opportunity, "value": 1})

            return {
                "nodes": nodes,
                "links": links,
                "summary": {
                    "total_paths": len(rows),
                    "distinct_anchors": len(set(n["name"] for n in nodes if n["category"] == "Memory Anchor")),
                    "distinct_opportunities": len(set(n["name"] for n in nodes if n["category"] == "Opportunity Area"))
                }
            }

scoring_manager = OpportunityScoringManager()
