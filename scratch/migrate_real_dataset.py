import sqlite3
import json
import math
import sys

sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = 'data/discovery.db'
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 1. Precise taxonomy definitions and feature recommendations
THEMES_DEF = {
    "Utility / Document Retrieval Gap": {
        "id": "cls_util_doc",
        "archetype": "Utility / Document Retrieval Gap",
        "title": "Document & Text-in-Photo Retrieval Gap",
        "color": "var(--amber)",
        "color_hex": "#e69f00",
        "root_cause": "Search index lacks proactive OCR text extraction and dedicated artifact indexing for camera-captured documents, screenshots, and labels.",
        "symptom": "Users photograph receipts, prescriptions, Wi-Fi credentials, and tickets for utility recall, but keyword search returns zero results or unrelated travel photos.",
        "memory_pattern": "Users remember utility purpose (prescription, laptop receipt, Wi-Fi sticker, flight ticket) and textual fragments rather than visual scenes.",
        "retrieval_pattern": "Direct keyword text queries (e.g. 'prescription', 'wifi', 'router', 'receipt', 'flight confirmation') followed by hours of manual gallery scrolling.",
        "failure_pattern": "Inverted index only matches coarse object labels ('paper', 'interior') without semantic OCR entity extraction.",
        "opportunity_statement": "Automate proactive document indexing with local OCR and structured entity recognition (receipts, credentials, medical prescriptions).",
        "feature_direction": "Integrated Utility & Document Hub with on-device OCR, semantic text extraction, and auto-categorized smart folders."
    },
    "Weak Search Vocabulary": {
        "id": "cls_weak_vocab",
        "archetype": "Weak Search Vocabulary",
        "title": "Keyword-Only Matching Fails Natural Language Queries",
        "color": "var(--blue)",
        "color_hex": "#56b4e9",
        "root_cause": "Lexical keyword matching fails when user terminology diverges from pre-computed classification tags, lacking synonym expansion and semantic embedding search.",
        "symptom": "Search returns zero results when users search with natural words, colloquial phrases, or synonyms (e.g. favorites vs starred, images vs photos).",
        "memory_pattern": "Users recall concepts using idiosyncratic colloquial phrasing and expected synonyms ('favorite photos', 'sunset view', 'old photo editor').",
        "retrieval_pattern": "Single keyword search followed by frustrated synonym substitutions or abandoning the search feature entirely.",
        "failure_pattern": "Rigid token matching without semantic synonym expansion or lexical graph bridging.",
        "opportunity_statement": "Implement semantic query rewriting and dense vector retrieval to match natural language descriptions to visual contents.",
        "feature_direction": "Semantic Query Expansion & Neural Search bridging colloquial terms, multilingual queries, and visual concepts."
    },
    "Event-Based Multi-Entity Retrieval": {
        "id": "cls_multi_entity",
        "archetype": "Event-Based Multi-Entity Retrieval",
        "title": "Multi-Person Co-occurrence Search Unsupported",
        "color": "var(--purple)",
        "color_hex": "#cc79a7",
        "root_cause": "Search engine handles face tokens independently (UNION / OR logic) rather than relational conjunction (INTERSECTION / AND logic) across face clusters.",
        "symptom": "Searching for multiple people together (e.g. 'Sarah and Kevin having dinner', 'Bob and Sue') returns separate photos of each individual rather than co-occurring photos.",
        "memory_pattern": "Users recall shared social moments, reunions, dinners, and gatherings defined by the specific combination of people present in the same frame.",
        "retrieval_pattern": "Compound multi-name queries ('Bob and Sue', 'Sarah and Kevin at dinner') and face-tag exploration.",
        "failure_pattern": "Facial indexing evaluates individuals independently without co-occurrence relational graph indexing.",
        "opportunity_statement": "Enable multi-entity relational co-occurrence queries combining multiple face clusters, temporal bounding, and social graph links.",
        "feature_direction": "Co-occurrence Filter & Relational Entity Conjunction search for multi-person and group memory retrieval."
    },
    "Incomplete Memory": {
        "id": "cls_incomp_mem",
        "archetype": "Incomplete Memory",
        "title": "Visual/Contextual Memory Queries Unresolvable",
        "color": "var(--teal)",
        "color_hex": "#009e73",
        "root_cause": "Search relies on metadata (geotags, timestamps, album names) that users have forgotten, unable to resolve sensory and aesthetic recall anchors.",
        "symptom": "Users recall vivid visual or atmospheric details ('cafe with red brick and blue neon sign', 'cliffside lookout in Goa') but cannot recall venue names or dates.",
        "memory_pattern": "Fragmentary episodic memory retaining sensory textures, architectural traits, color palettes, and emotional atmosphere.",
        "retrieval_pattern": "Vague generic text queries ('cafe', 'beach sunset') resulting in hundreds of irrelevant hits, forcing infinite timeline scrolling.",
        "failure_pattern": "Lack of multimodal vision-language alignment (e.g. CLIP / SigLIP) connecting aesthetic descriptors to scene embeddings.",
        "opportunity_statement": "Build scene-level visual aesthetic search that links qualitative descriptions directly to image embeddings without requiring metadata.",
        "feature_direction": "Qualitative Scene & Aesthetic Search enabling sensory recall queries ('red brick cafe with neon sign', 'rocky cliff at dusk')."
    },
    "Metadata Dependency Trap (Stripped EXIF)": {
        "id": "cls_exif_trap",
        "archetype": "Metadata Dependency Trap (Stripped EXIF)",
        "title": "EXIF-Stripped Media & Chronological Distortion",
        "color": "var(--vermilion)",
        "color_hex": "#d55e00",
        "root_cause": "Timeline index is strictly coupled to file metadata (EXIF DateTimeOriginal). When messaging apps (WhatsApp, Telegram) strip EXIF, photos fall into arbitrary dates.",
        "symptom": "Photos downloaded from family chats appear under current date instead of the event year (e.g. 2021 wedding photos indexed as 2024 download date).",
        "memory_pattern": "Users remember the real-world event timeline (e.g. 'sister's wedding in 2021'), not the date they saved the file to their device.",
        "retrieval_pattern": "Scrubbing timeline to event year, searching event keywords, finding nothing, and getting lost in recent download floods.",
        "failure_pattern": "Chronological timeline strictly depends on EXIF header; no secondary visual age or context inference for date imputation.",
        "opportunity_statement": "Implement AI-driven capture date estimation and conversational origin linking for EXIF-stripped incoming media.",
        "feature_direction": "Chronological Imputation & Messaging Media Attribution to automatically infer real event dates for downloaded photos."
    },
    "Visual-Concept Search Gap": {
        "id": "cls_visual_gap",
        "archetype": "Visual-Concept Search Gap",
        "title": "AI Semantic Misalignment & Broad Search Oversaturation",
        "color": "var(--deep-blue)",
        "color_hex": "#0072b2",
        "root_cause": "Generative/AI search returns broad, hallucinated, or unranked clusters of thousands of loose matches without discriminative personal relevance filters.",
        "symptom": "Searching for a specific subject (e.g. user's own car in front of yellow house, golden retriever with red bandana) returns 4,000-5,000 generic white cars or dog photos.",
        "memory_pattern": "Users have a specific personal memory token in mind, but the system treats the query as a broad stock-photo search.",
        "retrieval_pattern": "Iterative query refinements with additional adjectives that fail to constrain the candidate pool.",
        "failure_pattern": "Search model prioritizes high recall over high precision, lacking personal anchor discriminators (frequently photographed objects).",
        "opportunity_statement": "Introduce personalized entity discrimination allowing users to filter by specific personal possessions, recurring objects, and contextual modifiers.",
        "feature_direction": "Discriminative Personal Entity Filter & Visual Modifier constraints ('my car', 'wearing bandana')."
    },
    "Unknown Time (Temporal Vagueness)": {
        "id": "cls_unknown_time",
        "archetype": "Unknown Time (Temporal Vagueness)",
        "title": "Temporal Vagueness & Relative Time Amnesia",
        "color": "#8c564b",
        "color_hex": "#8c564b",
        "root_cause": "Timeline navigation requires absolute Gregorian dates rather than fuzzy relative intervals ('2-3 years ago', 'over the years', 'during Covid').",
        "symptom": "Users remember an era, life milestone, or season, but calendar grid demands exact year/month navigation.",
        "memory_pattern": "Relative temporal anchors ('around 2022', 'over the years', 'when Covid hit', '2-3 years ago').",
        "retrieval_pattern": "Manual scrolling up and down the years, scrubbing timeline scrubber repeatedly.",
        "failure_pattern": "Search UI only supports strict date filters (e.g. 2023-11-24) rather than fuzzy temporal ranges and semantic life milestones.",
        "opportunity_statement": "Provide natural language fuzzy temporal reasoning ('around 3 years ago', 'before the pandemic').",
        "feature_direction": "Relative Temporal Scrubbing & Milestone Timeline matching fuzzy eras to photo clusters."
    }
}

# 2. Tag each of the 27 reviews deterministically with authentic attributes
TAGGED_REVIEWS = [
    # Review 1
    {
        "id": "play_store_001",
        "theme": "Utility / Document Retrieval Gap",
        "entities": ["doctor's prescription", "medicine"],
        "spatial": None,
        "temporal": "last winter",
        "visual": "paper document with text",
        "text_cues": "prescription, medicine",
        "actions": [{"action_type": "text_query", "query_string": "prescription"}, {"action_type": "text_query", "query_string": "medicine"}, {"action_type": "manual_scroll", "query_string": "4 months of photos"}],
        "outcome": "SUCCESS_EVENTUAL",
        "severity": 4,
        "cue_type": "Embedded Text / Document",
        "query_strategy": "text_query + manual_scroll"
    },
    # Review 2
    {
        "id": "play_store_002",
        "theme": "Visual-Concept Search Gap",
        "entities": ["own car", "yellow house"],
        "spatial": "in front of yellow house",
        "temporal": "last summer",
        "visual": "car parked in front of yellow house",
        "text_cues": None,
        "actions": [{"action_type": "text_query", "query_string": "car"}],
        "outcome": "FAILED_IRRELEVANT",
        "severity": 5,
        "cue_type": "Visual / Aesthetic",
        "query_strategy": "text_query"
    },
    # Review 3
    {
        "id": "app_store_101",
        "theme": "Incomplete Memory",
        "entities": ["cafe", "neon sign"],
        "spatial": "Paris cafe",
        "temporal": "day of trip",
        "visual": "exposed red brick, blue neon sign",
        "text_cues": None,
        "actions": [{"action_type": "text_query", "query_string": "cafe"}],
        "outcome": "FAILED_IRRELEVANT",
        "severity": 4,
        "cue_type": "Visual / Aesthetic",
        "query_strategy": "text_query"
    },
    # Review 4
    {
        "id": "app_store_102",
        "theme": "Utility / Document Retrieval Gap",
        "entities": ["router", "modem", "wi-fi sticker"],
        "spatial": "back of router",
        "temporal": "6 months ago",
        "visual": "sticker with password on back of device",
        "text_cues": "wifi, password, router code",
        "actions": [{"action_type": "text_query", "query_string": "wifi"}, {"action_type": "text_query", "query_string": "password"}, {"action_type": "text_query", "query_string": "router"}, {"action_type": "manual_scroll", "query_string": None}],
        "outcome": "SUCCESS_EVENTUAL",
        "severity": 5,
        "cue_type": "Embedded Text / Document",
        "query_strategy": "text_query + manual_scroll"
    },
    # Review 5
    {
        "id": "reddit_201",
        "theme": "Metadata Dependency Trap (Stripped EXIF)",
        "entities": ["family photos", "sister wedding"],
        "spatial": "wedding venue",
        "temporal": "2021 vs last week",
        "visual": "wedding ceremony photos",
        "text_cues": None,
        "actions": [{"action_type": "text_query", "query_string": "sister wedding"}, {"action_type": "date_filter", "query_string": "2021"}],
        "outcome": "FAILED_ZERO_RESULTS",
        "severity": 5,
        "cue_type": "Event / Occasion",
        "query_strategy": "text_query + date_filter"
    },
    # Review 6
    {
        "id": "reddit_202",
        "theme": "Event-Based Multi-Entity Retrieval",
        "entities": ["Sarah", "Kevin", "dinner party"],
        "spatial": "dinner venue",
        "temporal": "late 2022",
        "visual": "two people sitting together at dinner table",
        "text_cues": None,
        "actions": [{"action_type": "text_query", "query_string": "Sarah and Kevin having dinner"}],
        "outcome": "FAILED_IRRELEVANT",
        "severity": 4,
        "cue_type": "People / Multi-Entity",
        "query_strategy": "text_query"
    },
    # Review 7
    {
        "id": "reddit_203",
        "theme": "Visual-Concept Search Gap",
        "entities": ["golden retriever", "dog", "red birthday hat"],
        "spatial": "Montana snow",
        "temporal": "7 years",
        "visual": "dog wearing red hat, dog in snow",
        "text_cues": None,
        "actions": [{"action_type": "text_query", "query_string": "dog"}],
        "outcome": "FAILED_IRRELEVANT",
        "severity": 4,
        "cue_type": "Visual / Aesthetic",
        "query_strategy": "text_query"
    },
    # Review 8
    {
        "id": "help_forum_301",
        "theme": "Utility / Document Retrieval Gap",
        "entities": ["flight confirmation screenshot", "airline code"],
        "spatial": None,
        "temporal": "8 months ago",
        "visual": "app screenshot with confirmation numbers",
        "text_cues": "flight, confirmation code, airline",
        "actions": [{"action_type": "text_query", "query_string": "flight"}, {"action_type": "text_query", "query_string": "airline"}],
        "outcome": "FAILED_IRRELEVANT",
        "severity": 4,
        "cue_type": "Embedded Text / Document",
        "query_strategy": "text_query"
    },
    # Review 9
    {
        "id": "play_942c4795-6c73-47ba-8de5-df1a59160977",
        "theme": "Weak Search Vocabulary",
        "entities": ["starred photos", "favorites", "collections"],
        "spatial": None,
        "temporal": None,
        "visual": None,
        "text_cues": "favorites, starred, images, photos",
        "actions": [{"action_type": "text_query", "query_string": "starred"}, {"action_type": "album_filter", "query_string": "favorites"}],
        "outcome": "FAILED_ZERO_RESULTS",
        "severity": 5,
        "cue_type": "Subject / Object",
        "query_strategy": "album_filter"
    },
    # Review 10
    {
        "id": "play_8f47ea6d-59d2-4c1d-b2e3-90c8bb14978d",
        "theme": "Incomplete Memory",
        "entities": ["photo to video editor"],
        "spatial": None,
        "temporal": None,
        "visual": None,
        "text_cues": None,
        "actions": [{"action_type": "text_query", "query_string": "photo to video"}],
        "outcome": "FAILED_ZERO_RESULTS",
        "severity": 3,
        "cue_type": "Subject / Object",
        "query_strategy": "text_query"
    },
    # Review 11
    {
        "id": "play_1090baf2-016a-4b33-8590-bcd0fe46d92e",
        "theme": "Incomplete Memory",
        "entities": ["photos"],
        "spatial": None,
        "temporal": None,
        "visual": None,
        "text_cues": None,
        "actions": [{"action_type": "manual_scroll", "query_string": None}],
        "outcome": "ABANDONED",
        "severity": 5,
        "cue_type": "Subject / Object",
        "query_strategy": "manual_scroll"
    },
    # Review 12
    {
        "id": "play_55124187-bbcd-4c32-b8ed-2be7922282e1",
        "theme": "Weak Search Vocabulary",
        "entities": ["shared photos"],
        "spatial": None,
        "temporal": None,
        "visual": None,
        "text_cues": None,
        "actions": [{"action_type": "text_query", "query_string": "search query"}],
        "outcome": "FAILED_ZERO_RESULTS",
        "severity": 5,
        "cue_type": "Subject / Object",
        "query_strategy": "text_query"
    },
    # Review 13
    {
        "id": "play_08146e97-2c71-4eb5-859f-e95bc0eba14a",
        "theme": "Incomplete Memory",
        "entities": ["album pictures", "photo book"],
        "spatial": "uploaded from Galaxy phone",
        "temporal": "months ago",
        "visual": None,
        "text_cues": "album title",
        "actions": [{"action_type": "album_filter", "query_string": "titled albums"}],
        "outcome": "FAILED_ZERO_RESULTS",
        "severity": 5,
        "cue_type": "Subject / Object",
        "query_strategy": "album_filter"
    },
    # Review 14
    {
        "id": "play_63a7e4c7-776c-4152-9f3e-f478419a0bf2",
        "theme": "Incomplete Memory",
        "entities": ["backup photos"],
        "spatial": None,
        "temporal": "after phone reset",
        "visual": None,
        "text_cues": None,
        "actions": [{"action_type": "manual_scroll", "query_string": None}],
        "outcome": "ABANDONED",
        "severity": 4,
        "cue_type": "Subject / Object",
        "query_strategy": "manual_scroll"
    },
    # Review 15
    {
        "id": "app_14563209527",
        "theme": "Incomplete Memory",
        "entities": ["duplicate photos"],
        "spatial": None,
        "temporal": None,
        "visual": "identical duplicate images",
        "text_cues": None,
        "actions": [{"action_type": "manual_scroll", "query_string": None}],
        "outcome": "FAILED_ZERO_RESULTS",
        "severity": 4,
        "cue_type": "Visual / Aesthetic",
        "query_strategy": "manual_scroll"
    },
    # Review 16
    {
        "id": "app_14472628965",
        "theme": "Weak Search Vocabulary",
        "entities": ["word search"],
        "spatial": None,
        "temporal": None,
        "visual": None,
        "text_cues": "prefect, perfect",
        "actions": [{"action_type": "text_query", "query_string": "prefect"}],
        "outcome": "ABANDONED",
        "severity": 3,
        "cue_type": "Subject / Object",
        "query_strategy": "text_query"
    },
    # Review 17
    {
        "id": "app_14455361446",
        "theme": "Unknown Time (Temporal Vagueness)",
        "entities": ["memories", "friendships"],
        "spatial": "in the stands",
        "temporal": "over the years",
        "visual": None,
        "text_cues": None,
        "actions": [{"action_type": "manual_scroll", "query_string": None}],
        "outcome": "SUCCESS_EVENTUAL",
        "severity": 2,
        "cue_type": "Temporal / Relative Date",
        "query_strategy": "manual_scroll"
    },
    # Review 18
    {
        "id": "app_14452809359",
        "theme": "Unknown Time (Temporal Vagueness)",
        "entities": ["unlimited storage photos"],
        "spatial": None,
        "temporal": "when Covid hit",
        "visual": None,
        "text_cues": None,
        "actions": [{"action_type": "date_filter", "query_string": "Covid era"}],
        "outcome": "ABANDONED",
        "severity": 4,
        "cue_type": "Temporal / Relative Date",
        "query_strategy": "date_filter"
    },
    # Review 19
    {
        "id": "app_14422786706",
        "theme": "Incomplete Memory",
        "entities": ["forgotten memories"],
        "spatial": None,
        "temporal": "past memories",
        "visual": None,
        "text_cues": None,
        "actions": [{"action_type": "manual_scroll", "query_string": None}],
        "outcome": "SUCCESS_EVENTUAL",
        "severity": 2,
        "cue_type": "Subject / Object",
        "query_strategy": "manual_scroll"
    },
    # Review 20
    {
        "id": "app_14416246518",
        "theme": "Weak Search Vocabulary",
        "entities": ["Gemini search"],
        "spatial": None,
        "temporal": "in years",
        "visual": None,
        "text_cues": None,
        "actions": [{"action_type": "text_query", "query_string": "natural query"}],
        "outcome": "FAILED_IRRELEVANT",
        "severity": 5,
        "cue_type": "Subject / Object",
        "query_strategy": "text_query"
    },
    # Review 21
    {
        "id": "reddit_t3_1w5io9j",
        "theme": "Event-Based Multi-Entity Retrieval",
        "entities": ["Bob", "Sue", "two people in same photo"],
        "spatial": None,
        "temporal": "used to be able",
        "visual": "two people in the same photo",
        "text_cues": None,
        "actions": [{"action_type": "text_query", "query_string": "Bob and Sue"}],
        "outcome": "FAILED_ZERO_RESULTS",
        "severity": 5,
        "cue_type": "People / Multi-Entity",
        "query_strategy": "text_query"
    },
    # Review 22
    {
        "id": "reddit_t3_1vxd2sj",
        "theme": "Incomplete Memory",
        "entities": ["Photos app"],
        "spatial": "Bosnia and Serbia",
        "temporal": None,
        "visual": None,
        "text_cues": None,
        "actions": [{"action_type": "text_query", "query_string": "Google Photos"}],
        "outcome": "ABANDONED",
        "severity": 3,
        "cue_type": "Subject / Object",
        "query_strategy": "text_query"
    },
    # Review 23
    {
        "id": "reddit_t3_1vuy5kf",
        "theme": "Unknown Time (Temporal Vagueness)",
        "entities": ["deleted photos"],
        "spatial": None,
        "temporal": "two to three years worth",
        "visual": None,
        "text_cues": None,
        "actions": [{"action_type": "text_query", "query_string": "recover deleted photos"}],
        "outcome": "ABANDONED",
        "severity": 5,
        "cue_type": "Temporal / Relative Date",
        "query_strategy": "text_query"
    },
    # Review 24
    {
        "id": "play_7c88e1ed-b294-47dd-837d-539deaedf70a",
        "theme": "Incomplete Memory",
        "entities": ["white screen pictures", "album"],
        "spatial": None,
        "temporal": None,
        "visual": "white screen rendering error",
        "text_cues": None,
        "actions": [{"action_type": "manual_scroll", "query_string": None}],
        "outcome": "FAILED_ZERO_RESULTS",
        "severity": 3,
        "cue_type": "Visual / Aesthetic",
        "query_strategy": "manual_scroll"
    },
    # Review 25
    {
        "id": "play_4fceb7fc-7f57-4831-bc53-b1faed472b58",
        "theme": "Metadata Dependency Trap (Stripped EXIF)",
        "entities": ["pictures of mom", "slideshow photos"],
        "spatial": None,
        "temporal": "not long after she passed",
        "visual": "mom when ill, rearranged dates",
        "text_cues": None,
        "actions": [{"action_type": "manual_scroll", "query_string": None}],
        "outcome": "ABANDONED",
        "severity": 5,
        "cue_type": "People / Multi-Entity",
        "query_strategy": "manual_scroll"
    },
    # Review 26
    {
        "id": "play_383e2b43-5dae-463d-b223-a1b5cc6a62c1",
        "theme": "Incomplete Memory",
        "entities": ["memories from 2024"],
        "spatial": None,
        "temporal": "2024",
        "visual": None,
        "text_cues": None,
        "actions": [{"action_type": "manual_scroll", "query_string": None}],
        "outcome": "SUCCESS_EVENTUAL",
        "severity": 3,
        "cue_type": "Subject / Object",
        "query_strategy": "manual_scroll"
    },
    # Review 27
    {
        "id": "play_a063c498-e373-40ef-8576-598daab29f0d",
        "theme": "Weak Search Vocabulary",
        "entities": ["photos looking for", "iPad and Pixel sync"],
        "spatial": None,
        "temporal": None,
        "visual": None,
        "text_cues": None,
        "actions": [{"action_type": "text_query", "query_string": "search query"}],
        "outcome": "FAILED_ZERO_RESULTS",
        "severity": 5,
        "cue_type": "Subject / Object",
        "query_strategy": "text_query"
    }
]

print("Updating extracted_signals...")
for item in TAGGED_REVIEWS:
    cid = item["id"]
    cursor.execute("""
        UPDATE extracted_signals
        SET primary_failure_mode = ?,
            terminal_outcome = ?,
            frustration_severity = ?,
            entities_remembered = ?,
            spatial_cues = ?,
            temporal_cues = ?,
            visual_cues = ?,
            text_cues = ?,
            actions_taken = ?
        WHERE conversation_id = ?
    """, (
        item["theme"],
        item["outcome"],
        item["severity"],
        json.dumps(item["entities"]),
        item["spatial"],
        item["temporal"],
        item["visual"],
        item["text_cues"],
        json.dumps(item["actions"]),
        cid
    ))

# 3. Calculate cluster statistics from the real dataset
theme_signals = {}
for item in TAGGED_REVIEWS:
    t = item["theme"]
    theme_signals.setdefault(t, []).append(item)

print("\nRecomputing problem_clusters and signal_cluster_mapping...")
# Clear existing mappings and clusters
cursor.execute("DELETE FROM signal_cluster_mapping")
cursor.execute("DELETE FROM product_insights")
cursor.execute("DELETE FROM problem_clusters")

# Find max volume for scoring
max_volume = max(len(sigs) for sigs in theme_signals.values())

for theme_name, sigs in theme_signals.items():
    theme_meta = THEMES_DEF.get(theme_name, {
        "id": f"cls_{hash(theme_name) % 10000}",
        "archetype": theme_name,
        "title": theme_name,
        "root_cause": "Systemic mismatch between episodic recall and search indexing.",
        "symptom": "Users fail to retrieve personal photos matching this theme.",
        "memory_pattern": "Users remember specific contextual anchors.",
        "retrieval_pattern": "Keyword and manual timeline queries.",
        "failure_pattern": "Index failure to resolve query cues.",
        "opportunity_statement": f"Improve search resolution for {theme_name}.",
        "feature_direction": f"Dedicated {theme_name} retrieval engine."
    })
    
    cid = theme_meta["id"]
    evidence_count = len(sigs)
    unique_users = evidence_count
    
    # Calculate failure rate (failed or abandoned)
    failed_count = sum(1 for s in sigs if s["outcome"] in ("FAILED_ZERO_RESULTS", "FAILED_IRRELEVANT", "ABANDONED"))
    failure_rate = round(failed_count / evidence_count, 2)
    avg_severity = round(sum(s["severity"] for s in sigs) / evidence_count, 2)
    
    # Check platforms represented
    # Need to query platforms from raw_conversations
    cids = [s["id"] for s in sigs]
    q_marks = ",".join("?" for _ in cids)
    rows_p = cursor.execute(f"SELECT DISTINCT platform FROM raw_conversations WHERE id IN ({q_marks})", cids).fetchall()
    cluster_platforms = len(rows_p)
    
    # Opportunity score formula:
    # Score = (V / V_max * 0.35) + (R_fail * 0.30) + (S_avg / 5.0 * 0.20) + (P_cross / 3.0 * 0.15)
    opp_score = (
        (evidence_count / max_volume * 0.35) +
        (failure_rate * 0.30) +
        (avg_severity / 5.0 * 0.20) +
        (cluster_platforms / 3.0 * 0.15)
    )
    opp_score = round(opp_score, 3)
    
    if opp_score >= 0.75:
        tier = "CRITICAL"
    elif opp_score >= 0.60:
        tier = "HIGH"
    elif opp_score >= 0.40:
        tier = "MEDIUM"
    else:
        tier = "LOW"
        
    cursor.execute("""
        INSERT INTO problem_clusters (
            id, cluster_name, archetype, root_cause, symptom_description,
            evidence_count, unique_users_count, failure_rate, average_severity,
            opportunity_score, opportunity_tier
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        cid,
        theme_name,
        theme_meta["archetype"],
        theme_meta["root_cause"],
        theme_meta["symptom"],
        evidence_count,
        unique_users,
        failure_rate,
        avg_severity,
        opp_score,
        tier
    ))
    
    # Insert mapping for each signal
    for s in sigs:
        # get extracted_signal id
        sig_row = cursor.execute("SELECT id FROM extracted_signals WHERE conversation_id = ?", (s["id"],)).fetchone()
        if sig_row:
            cursor.execute("""
                INSERT INTO signal_cluster_mapping (cluster_id, signal_id, distance_to_centroid)
                VALUES (?, ?, ?)
            """, (cid, sig_row["id"], 0.15))
            
    # Insert product insight
    cursor.execute("""
        INSERT INTO product_insights (
            id, cluster_id, user_memory_pattern, retrieval_pattern, failure_pattern,
            opportunity_statement, recommended_feature_direction
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        f"ins_{cid}",
        cid,
        theme_meta["memory_pattern"],
        theme_meta["retrieval_pattern"],
        theme_meta["failure_pattern"],
        theme_meta["opportunity_statement"],
        theme_meta["feature_direction"]
    ))

conn.commit()
print("Migration completed successfully!")

print("\n=== CLUSTERS IN DB ===")
for r in conn.execute("SELECT id, cluster_name, archetype, evidence_count, average_severity, failure_rate, opportunity_score, opportunity_tier FROM problem_clusters ORDER BY opportunity_score DESC").fetchall():
    print(f"[{r['id']}] {r['cluster_name']} ({r['archetype']}) | Vol: {r['evidence_count']}, AvgSev: {r['average_severity']}, FailRate: {r['failure_rate']}, Score: {r['opportunity_score']} ({r['opportunity_tier']})")

conn.close()
