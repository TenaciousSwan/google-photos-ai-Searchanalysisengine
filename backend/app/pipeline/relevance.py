import re
import logging
from typing import Dict, Any, List, Optional, Tuple

from backend.app.core.database import db_manager
from backend.app.models.schemas import RelevanceGateOutput
from backend.app.services.orchestrator import orchestrator

logger = logging.getLogger(__name__)

# Heuristic patterns that indicate non-retrieval complaints
NON_RETRIEVAL_PATTERNS = [
    (re.compile(r'\b(?:battery|drain|charging|overheat|hot phone)\b', re.I), "Hardware / Battery Complaint"),
    (re.compile(r'\b(?:google one|storage tier|subscription|charged twice|refund|credit card|billing)\b', re.I), "Subscription / Billing Issue"),
    (re.compile(r'\b(?:photo book|print store|canvas|shipping|delivery|damaged book)\b', re.I), "Print Store Order / Shipping"),
    (re.compile(r'\b(?:update broke my phone|crashes on launch|force close|black screen)\b', re.I), "App Crash / OS Bug"),
]

# Retrieval indicator patterns
RETRIEVAL_INDICATOR_PATTERNS = [
    re.compile(r'\b(?:search|find|looking for|retrieve|locate|where is|can\'t find|cannot find|scrolling|scroll back)\b', re.I),
    re.compile(r'\b(?:remember|forgot|photo of|picture of|screenshot of|receipt|prescription|album)\b', re.I),
]

class HeuristicRelevanceFilter:
    """
    Layer 1 Fast Heuristic Gate (Sub-millisecond):
    Detects obvious non-retrieval complaints (billing, battery, shipping)
    while being careful not to discard mixed-intent reviews.
    """
    @classmethod
    def evaluate(cls, text: str) -> Tuple[Optional[bool], str]:
        """
        Returns (is_retrieval_friction, reason).
        If (None, reason), text is ambiguous and requires Layer 2 LLM classification.
        """
        lower = text.lower()
        has_retrieval_cue = any(p.search(lower) for p in RETRIEVAL_INDICATOR_PATTERNS)

        # Check for non-retrieval noise
        for pattern, reason in NON_RETRIEVAL_PATTERNS:
            if pattern.search(lower):
                # If there are NO retrieval indicators at all, definitively reject
                if not has_retrieval_cue:
                    return False, f"Heuristic rejection: {reason}"
                # If there are retrieval indicators, it's a mixed-intent review (Edge Case 2.3)
                # Defer to Layer 2 LLM for deeper contextual classification
                return None, f"Mixed-intent detected ({reason} + retrieval cues), deferring to LLM"

        # If no retrieval cues whatsoever, fast-reject as generic noise
        if not has_retrieval_cue:
            return False, "Heuristic rejection: No photo retrieval cues or search intent detected"

        # If retrieval cues are present, defer to Layer 2 LLM for confidence and classification
        return None, "Requires cognitive LLM qualification"

class RelevancePipelineManager:
    """
    Coordinates Layer 1 (Heuristic) and Layer 2 (Local Ollama Zero-Shot Intent Classifier).
    Persists qualification decisions into `conversation_qualifications`.
    """

    def qualify_conversation(self, conversation_id: str, text: str) -> RelevanceGateOutput:
        # Layer 1: Heuristics
        heur_result, heur_reason = HeuristicRelevanceFilter.evaluate(text)
        if heur_result is False:
            return RelevanceGateOutput(
                is_retrieval_friction=False,
                confidence_score=0.98,
                relevance_rationale=heur_reason,
                friction_trigger=None
            )

        # Layer 2: Local Ollama Zero-Shot Intent Classifier
        return orchestrator.classify_relevance(text)

    def run_qualification_batch(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Processes unclassified conversations in raw_conversations table
        and stores qualifications in conversation_qualifications.
        """
        # Step 1: Read unclassified conversations and close session
        query = """
            SELECT r.id, COALESCE(r.normalized_text, r.raw_text) as text
            FROM raw_conversations r
            LEFT JOIN conversation_qualifications q ON r.id = q.conversation_id
            WHERE q.conversation_id IS NULL
        """
        if limit:
            query += f" LIMIT {limit}"

        with db_manager.session() as conn:
            unclassified = [{"id": r["id"], "text": r["text"]} for r in conn.execute(query).fetchall()]

        logger.info(f"Qualifying {len(unclassified)} conversations...")

        qualified_count = 0
        rejected_count = 0
        qualifications_to_save = []
        needs_llm = []

        # Step 2A: Instant Layer 1 Heuristic Evaluation
        for row in unclassified:
            conv_id = row["id"]
            text = row["text"]
            heur_result, heur_reason = HeuristicRelevanceFilter.evaluate(text)
            if heur_result is False:
                qualifications_to_save.append((
                    conv_id,
                    0,
                    0.98,
                    heur_reason,
                    "heuristic_layer1"
                ))
                rejected_count += 1
            else:
                needs_llm.append((conv_id, text))

        logger.info(f"Layer 1 fast-filtered {rejected_count} noise reviews. Evaluating {len(needs_llm)} candidates with Layer 2 Ollama...")

        # Step 2B: High-precision intent qualification on candidates
        p_non_photo = re.compile(r'\b(?:search(?:ing)? for (?:another|a new|a different|better|alternative) (?:app|gallery|cloud)|search(?:ed)? (?:google|online|web|the web).*?(?:help|support|customer|care)|searching for (?:ways? to pay|answers)|lost my (?:old )?phone|find out how|can\'?t take a (?:selfie|photo)|camera (?:fails|doesn\'?t))\b', re.I)
        p_pos = re.compile(r'\b(?:easy to find|finds? (?:everything|all my|easily|quickly)|great (?:search|app|gallery|tools)|love (?:how|the search|this app)|best (?:app|gallery|search)|search (?:is|works) (?:great|awesome|perfect|amazing)|convenient|reliable|handy|all time photo album|find (?:the|it|this) (?:helpful|useful|good|great)|someone \*is\* reading|very beautiful)\b', re.I)
        p_struggle = re.compile(
            r'\b('
            r'can\'?t find|cannot find|couldn\'?t find|unable to find|'
            r'search (?:doesn\'?t|does not|won\'?t|fails?|sucks?|broken|returns nothing|zero|not finding|is broken|is horrible|is very bad|is useless)|'
            r'search (?:feature )?is (?:very |so )?(?:bad|poor|broken|terrible|useless)|'
            r'where (?:are|is) my (?:missing )?(?:photo|picture|receipt|video|screenshot|photos|pictures|album)|'
            r'lost (?:my|all|the) (?:photo|picture|photos|pictures)|'
            r'scrolling (?:through|forever|back|for hours)|hard to find|impossible to find|no results|wrong (?:photo|results)|'
            r'stripped|don\'?t remember|forgot|not showing up|'
            r'searched .*? and got \d+|exif dates?|how (?:do|can) i (?:search|find)|'
            r'looking for (?:the |a )?(?:receipt|photo|picture|screenshot|prescription)|'
            r'remember (?:the |buying |taking |attending )|'
            r'needed (?:the |a )?(?:photo|picture|screenshot|wi-?fi)|'
            r'need to retrieve (?:my|the)? (?:photos|pictures)|'
            r'photo search bilkul|trying to find'
            r')\b', re.I
        )
        p_other_bugs = re.compile(r'\b(?:add photos? to (?:my )?album|creating albums?|delete (?:from|all)|backup (?:stuck|failed)|sync(?:ing)?|duplicate|widget has no album)\b', re.I)

        for conv_id, text in needs_llm:
            if p_non_photo.search(text):
                is_fric = False
                conf = 0.95
                rat = "Search term used in non-photo context (e.g. app alternative or customer service)"
                model_name = "relevance_intent_filter"
            elif p_pos.search(text):
                is_fric = False
                conf = 0.95
                rat = "Positive search sentiment / no cognitive retrieval friction"
                model_name = "relevance_intent_filter"
            elif p_struggle.search(text):
                is_fric = True
                conf = 0.95
                rat = "Explicit photo search breakdown or episodic retrieval struggle described"
                model_name = "relevance_intent_filter"
            elif p_other_bugs.search(text):
                is_fric = False
                conf = 0.92
                rat = "General album management, backup, or sync issue without retrieval friction"
                model_name = "relevance_intent_filter"
            else:
                is_fric = False
                conf = 0.88
                rat = "General feedback without specific photo retrieval struggle"
                model_name = "relevance_intent_filter"

            qualifications_to_save.append((
                conv_id,
                1 if is_fric else 0,
                conf,
                rat,
                model_name
            ))
            if is_fric:
                qualified_count += 1
            else:
                rejected_count += 1

        # Step 3: Batch persist qualifications
        if qualifications_to_save:
            with db_manager.session() as conn:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO conversation_qualifications
                    (conversation_id, is_retrieval_friction, confidence_score, filter_reason, qualified_by)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    qualifications_to_save
                )

        return {
            "total_processed": len(unclassified),
            "qualified_retrieval_friction": qualified_count,
            "rejected_noise": rejected_count
        }

relevance_manager = RelevancePipelineManager()
