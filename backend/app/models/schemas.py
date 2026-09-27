from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime

class OutcomeEnum(str, Enum):
    SUCCESS_INSTANT = "SUCCESS_INSTANT"
    SUCCESS_EVENTUAL = "SUCCESS_EVENTUAL"
    FAILED_ZERO_RESULTS = "FAILED_ZERO_RESULTS"
    FAILED_IRRELEVANT = "FAILED_IRRELEVANT"
    ABANDONED = "ABANDONED"
    EXTERNAL_WORKAROUND = "EXTERNAL_WORKAROUND"

class PriorityTierEnum(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

# Stage 1 Schema: Raw Ingested Review / Conversation
class RawConversation(BaseModel):
    id: str = Field(description="Unique conversation or review ID")
    source: str = Field(description="Platform name: play_store, app_store, reddit, help_forum")
    source_url: Optional[str] = None
    post_date: str = Field(description="ISO or date string")
    platform: str = Field(description="android, ios, web")
    author_pseudonym: Optional[str] = "Anonymous"
    raw_text: str = Field(description="Verbatim user text")
    normalized_text: Optional[str] = None
    star_rating: Optional[int] = None
    engagement_count: Optional[int] = 0

    model_config = ConfigDict(from_attributes=True)

# Stage 2 Schema: Relevance & Friction Qualification
class RelevanceGateOutput(BaseModel):
    is_retrieval_friction: bool = Field(description="True if user describes finding a photo with incomplete memory")
    confidence_score: float = Field(ge=0.0, le=1.0, description="Confidence in classification")
    relevance_rationale: str = Field(description="Brief reason for qualification")
    friction_trigger: Optional[str] = Field(None, description="e.g. lost screenshot, forgot date, failed search")

# Stage 3 Schema: Cognitive Memory Signals
class MemorySignals(BaseModel):
    entities_remembered: List[str] = Field(default_factory=list, description="People, pets, objects recalled")
    spatial_cues: Optional[str] = Field(None, description="Setting, venue type, beach, coffee shop")
    temporal_cues: Optional[str] = Field(None, description="Vague/relative time: 'last summer', '2 years ago'")
    visual_aesthetic_cues: Optional[str] = Field(None, description="Colors, lighting, framing, distinct visual traits")
    embedded_text_cues: Optional[str] = Field(None, description="OCR text or numbers user recalls seeing on photo")

    @classmethod
    def _coerce_str(cls, v: Any) -> Optional[str]:
        if isinstance(v, list):
            return ", ".join(str(item) for item in v if item)
        return str(v) if v is not None else None

    @field_validator("spatial_cues", "temporal_cues", "visual_aesthetic_cues", "embedded_text_cues", mode="before")
    @classmethod
    def handle_cues(cls, v: Any) -> Optional[str]:
        return cls._coerce_str(v)

class ForgottenSignals(BaseModel):
    exact_date_forgotten: bool = Field(default=True, description="User does not know exact calendar date")
    exact_location_forgotten: bool = Field(default=False, description="User does not know exact place name/geotag")
    filename_forgotten: bool = Field(default=True, description="User does not know file name")
    album_name_forgotten: bool = Field(default=False, description="User does not know or did not create album")

class RetrievalAction(BaseModel):
    action_type: str = Field(description="text_query, face_tag, manual_scroll, map_filter, lens")
    query_string: Optional[str] = None

class CognitiveExtractionPayload(BaseModel):
    conversation_id: str
    memory_signals: MemorySignals
    forgotten_signals: ForgottenSignals
    actions_taken: List[RetrievalAction] = Field(default_factory=list)
    outcome: OutcomeEnum
    user_frustration_level: int = Field(ge=1, le=5, description="1=Mild, 5=Severe churn risk")
    primary_failure_mode: str = Field(description="Core breakdown reason")

# Stage 4 & 5 Schema: Problem Cluster
class ProblemCluster(BaseModel):
    id: str
    cluster_name: str
    archetype: str
    root_cause: str
    symptom_description: str
    evidence_count: int = 0
    unique_users_count: int = 0
    failure_rate: float = 0.0
    average_severity: float = 0.0
    opportunity_score: float = 0.0
    opportunity_tier: PriorityTierEnum = PriorityTierEnum.LOW

# Stage 6 & 7 Schema: Product Discovery Card
class DiscoveryCardSynthesis(BaseModel):
    user_memory_pattern: str = Field(description="Psychological memory anchors users recall (sensory, spatial, relative time, etc.)")
    retrieval_pattern: str = Field(description="Exact search syntax and exploration actions attempted by users")
    failure_pattern: str = Field(description="Systemic and architectural failure mechanism in photo indexing/search")
    opportunity_statement: str = Field(description="Core strategic opportunity statement for Google Photos product team")
    recommended_feature_direction: str = Field(description="Actionable technical and UX feature concept recommendation")

class ProductInsight(BaseModel):
    id: str
    cluster_id: str
    user_memory_pattern: str
    retrieval_pattern: str
    failure_pattern: str
    opportunity_statement: str
    recommended_feature_direction: str

# Overview Metrics Schema
class OverviewMetrics(BaseModel):
    total_sources_collected: int = 0
    total_conversations: int = 0
    relevant_conversations: int = 0
    unique_users: int = 0
    system_failure_rate: float = 0.0
    average_severity: float = 0.0
    platforms_represented: List[str] = Field(default_factory=list)
    top_opportunity_archetype: Optional[str] = None
