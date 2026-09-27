import sqlite3
import hashlib
import json
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Any, Dict
from backend.app.core.config import settings

SCHEMA_SQL = """
-- Raw user conversations from public sources
CREATE TABLE IF NOT EXISTS raw_conversations (
    id VARCHAR(64) PRIMARY KEY,
    source VARCHAR(32) NOT NULL, -- 'play_store', 'app_store', 'reddit', 'help_forum'
    source_url TEXT,
    post_date TEXT NOT NULL,
    platform VARCHAR(16) NOT NULL, -- 'android', 'ios', 'web'
    author_pseudonym VARCHAR(64),
    raw_text TEXT NOT NULL,
    normalized_text TEXT,          -- Produced by Ollama normalization
    star_rating INTEGER,
    engagement_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Relevance qualification output (Ollama)
CREATE TABLE IF NOT EXISTS conversation_qualifications (
    conversation_id VARCHAR(64) PRIMARY KEY REFERENCES raw_conversations(id) ON DELETE CASCADE,
    is_retrieval_friction BOOLEAN NOT NULL,
    confidence_score FLOAT NOT NULL,
    filter_reason TEXT,
    qualified_by VARCHAR(32) DEFAULT 'ollama_llama3.2',
    qualified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Extracted cognitive memory and retrieval signals (Gemini / Ollama Fallback)
CREATE TABLE IF NOT EXISTS extracted_signals (
    id VARCHAR(64) PRIMARY KEY,
    conversation_id VARCHAR(64) REFERENCES raw_conversations(id) ON DELETE CASCADE,
    entities_remembered TEXT,       -- JSON array of entities
    spatial_cues TEXT,              -- Visual/spatial memory
    temporal_cues TEXT,             -- Vague/relative temporal memory
    visual_cues TEXT,               -- Visual traits/aesthetic memory
    text_cues TEXT,                 -- Embedded OCR text recalled
    date_forgotten BOOLEAN DEFAULT 1,
    location_forgotten BOOLEAN DEFAULT 0,
    filename_forgotten BOOLEAN DEFAULT 1,
    actions_taken TEXT,             -- JSON array of attempts
    terminal_outcome VARCHAR(32) NOT NULL,
    frustration_severity INTEGER CHECK(frustration_severity BETWEEN 1 AND 5),
    primary_failure_mode TEXT NOT NULL,
    extracted_by VARCHAR(32) DEFAULT 'gemini-1.5-flash'
);

-- Dynamically emergent problem clusters
CREATE TABLE IF NOT EXISTS problem_clusters (
    id VARCHAR(64) PRIMARY KEY,
    cluster_name VARCHAR(128) NOT NULL,
    archetype VARCHAR(64) NOT NULL,
    root_cause TEXT NOT NULL,
    symptom_description TEXT NOT NULL,
    evidence_count INTEGER NOT NULL,
    unique_users_count INTEGER NOT NULL,
    failure_rate FLOAT NOT NULL,
    average_severity FLOAT NOT NULL,
    opportunity_score FLOAT NOT NULL,
    opportunity_tier VARCHAR(16) NOT NULL -- 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
);

-- Mapping table linking extracted signals to problem clusters
CREATE TABLE IF NOT EXISTS signal_cluster_mapping (
    signal_id VARCHAR(64) REFERENCES extracted_signals(id) ON DELETE CASCADE,
    cluster_id VARCHAR(64) REFERENCES problem_clusters(id) ON DELETE CASCADE,
    distance_to_centroid FLOAT,
    PRIMARY KEY (signal_id, cluster_id)
);

-- Synthesized Product Discovery Cards
CREATE TABLE IF NOT EXISTS product_insights (
    id VARCHAR(64) PRIMARY KEY,
    cluster_id VARCHAR(64) REFERENCES problem_clusters(id) ON DELETE CASCADE,
    user_memory_pattern TEXT NOT NULL,
    retrieval_pattern TEXT NOT NULL,
    failure_pattern TEXT NOT NULL,
    opportunity_statement TEXT NOT NULL,
    recommended_feature_direction TEXT NOT NULL
);

-- Model invocation cache for zero-waste repeatability
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key VARCHAR(64) PRIMARY KEY, -- MD5 of (model, prompt, input)
    model_name VARCHAR(64) NOT NULL,
    response_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Checkpoints for scraping resume capability
CREATE TABLE IF NOT EXISTS ingestion_checkpoints (
    source VARCHAR(32) PRIMARY KEY,
    last_page INTEGER DEFAULT 0,
    last_processed_id VARCHAR(64),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

class DatabaseManager:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.DB_PATH

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        return conn

    @contextmanager
    def session(self):
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self):
        """Creates tables and indexes if they do not exist."""
        with self.session() as conn:
            conn.executescript(SCHEMA_SQL)
            # Create helpful indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_source ON raw_conversations(source);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_date ON raw_conversations(post_date);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_qual_friction ON conversation_qualifications(is_retrieval_friction);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_outcome ON extracted_signals(terminal_outcome);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_clusters_tier ON problem_clusters(opportunity_tier);")

    # Cache helper functions
    @staticmethod
    def compute_cache_key(model_name: str, prompt: str, input_text: str) -> str:
        content = f"{model_name}::{prompt}::{input_text}".encode("utf-8")
        return hashlib.md5(content).hexdigest()

    def get_cached_response(self, cache_key: str) -> Optional[Dict[str, Any]]:
        with self.session() as conn:
            cursor = conn.execute("SELECT response_json FROM llm_cache WHERE cache_key = ?", (cache_key,))
            row = cursor.fetchone()
            if row:
                try:
                    return json.loads(row["response_json"])
                except json.JSONDecodeError:
                    return None
            return None

    def set_cached_response(self, cache_key: str, model_name: str, response_data: Any):
        json_str = json.dumps(response_data) if not isinstance(response_data, str) else response_data
        with self.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (cache_key, model_name, response_json) VALUES (?, ?, ?)",
                (cache_key, model_name, json_str)
            )

db_manager = DatabaseManager()
