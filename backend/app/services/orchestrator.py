import logging
from typing import Optional, Dict, Any, Type
from pydantic import BaseModel

from backend.app.core.config import settings
from backend.app.core.rate_limiter import TokenBucketRateLimiter
from backend.app.core.database import db_manager
from backend.app.services.ollama_client import ollama_client, OllamaClient
from backend.app.services.gemini_client import gemini_client, GeminiClient, RateLimitException
from backend.app.models.schemas import RelevanceGateOutput, CognitiveExtractionPayload

logger = logging.getLogger(__name__)

class LLMOrchestrator:
    """
    Hybrid Dual-LLM Orchestrator coordinating Google Gemini Free Tier
    and Local Ollama. Provides:
      1. Zero-waste MD5 disk caching in SQLite.
      2. 14 RPM Token Bucket rate limiter for Gemini Free Tier.
      3. Seamless circuit-breaker fallback to Ollama on HTTP 429/quota exhaustion.
      4. Task-based routing: Bulk scraping & embeddings -> Ollama; Cognitive reasoning -> Gemini/Ollama.
    """
    def __init__(
        self,
        gemini: Optional[GeminiClient] = None,
        ollama: Optional[OllamaClient] = None,
        rpm_limit: int = 14
    ):
        self.gemini = gemini or gemini_client
        self.ollama = ollama or ollama_client
        self.rate_limiter = TokenBucketRateLimiter(rpm=rpm_limit)
        self.total_gemini_calls = 0
        self.total_ollama_calls = 0
        self.total_cached_hits = 0
        self.total_failovers = 0

    def get_status(self) -> Dict[str, Any]:
        """Returns health and status of both engines and cache."""
        ollama_ok = self.ollama.is_available()
        gemini_ok = self.gemini.is_available()
        return {
            "gemini_configured": gemini_ok,
            "gemini_model": self.gemini.model_name,
            "gemini_tokens_available": round(self.rate_limiter.get_available_tokens(), 2),
            "ollama_available": ollama_ok,
            "ollama_base_url": self.ollama.base_url,
            "ollama_model": self.ollama.default_model,
            "ollama_installed_models": self.ollama.get_installed_models() if ollama_ok else [],
            "stats": {
                "gemini_calls": self.total_gemini_calls,
                "ollama_calls": self.total_ollama_calls,
                "cached_hits": self.total_cached_hits,
                "failovers": self.total_failovers
            }
        }

    def run_structured(
        self,
        prompt: str,
        response_schema: Type[BaseModel],
        system_instruction: Optional[str] = None,
        prefer_engine: str = "gemini"
    ) -> Dict[str, Any]:
        """
        Executes structured JSON generation with caching and transparent failover.
        """
        # 1. Check disk cache
        cache_key = db_manager.compute_cache_key(
            model_name=f"{prefer_engine}::{response_schema.__name__}",
            prompt=system_instruction or "",
            input_text=prompt
        )
        cached = db_manager.get_cached_response(cache_key)
        if cached is not None:
            self.total_cached_hits += 1
            return cached

        # 2. Try primary engine (Gemini) if preferred and available
        if prefer_engine == "gemini" and self.gemini.is_available():
            try:
                # Rate limit check (acquire token)
                self.rate_limiter.acquire(wait=True)
                result = self.gemini.generate_structured(
                    prompt=prompt,
                    response_schema=response_schema,
                    system_instruction=system_instruction
                )
                self.total_gemini_calls += 1
                db_manager.set_cached_response(cache_key, self.gemini.model_name, result)
                return result
            except RateLimitException as e:
                logger.warning(f"Gemini Free Tier rate limit hit! Failing over to local Ollama. Reason: {e}")
                self.total_failovers += 1
            except Exception as e:
                logger.error(f"Gemini generation error: {e}. Falling over to local Ollama.")
                self.total_failovers += 1

        # 3. Fallback / Direct Route to Local Ollama
        json_prompt = (
            f"{system_instruction or ''}\n\n"
            f"Input:\n{prompt}\n\n"
            f"Respond ONLY with a valid JSON object strictly matching this schema structure:\n"
            f"{response_schema.model_json_schema()}"
        )
        result = self.ollama.generate_json(prompt=json_prompt)
        self.total_ollama_calls += 1
        db_manager.set_cached_response(cache_key, f"ollama::{self.ollama.default_model}", result)
        return result

    def normalize_text(self, raw_text: str) -> str:
        """
        Normalizes noisy scraped review text using local Ollama (zero API cost).
        Strips markdown, broken unicode, and colloquial internet slang.
        """
        cache_key = db_manager.compute_cache_key("ollama_normalize", "clean_text", raw_text)
        cached = db_manager.get_cached_response(cache_key)
        if cached:
            return cached.get("normalized_text", raw_text)

        system_prompt = (
            "You are a text normalization engine. Clean the user review by removing broken unicode, "
            "HTML tags, and converting colloquial internet slang into clean, readable English text. "
            "Preserve the exact meaning and sentiment. Return ONLY the cleaned text with no extra commentary."
        )
        
        if self.ollama.is_available():
            cleaned = self.ollama.generate(prompt=raw_text, system_prompt=system_prompt, temperature=0.1)
            cleaned = cleaned.strip().strip('"')
            self.total_ollama_calls += 1
            db_manager.set_cached_response(cache_key, "ollama_normalize", {"normalized_text": cleaned})
            return cleaned
        return raw_text.strip()

    def classify_relevance(self, text: str) -> RelevanceGateOutput:
        """
        Fast zero-shot intent classifier to filter photo retrieval friction from noise.
        Runs locally on Ollama to protect Gemini quotas.
        """
        system_instruction = (
            "You are a relevance classifier for a photo retrieval discovery engine. "
            "Determine if the user feedback describes difficulty finding, searching for, "
            "or retrieving a personal photograph or album when memory is incomplete. "
            "If the complaint is solely about cloud storage pricing, Google One billing, "
            "battery drain, or app crashes, is_retrieval_friction MUST be false."
        )
        res = self.run_structured(
            prompt=text,
            response_schema=RelevanceGateOutput,
            system_instruction=system_instruction,
            prefer_engine="ollama"  # Save Gemini quotas for cognitive extraction
        )
        try:
            return RelevanceGateOutput(**res)
        except Exception:
            return RelevanceGateOutput(
                is_retrieval_friction=False,
                confidence_score=0.5,
                relevance_rationale="Fallback parsing default"
            )

    def extract_cognitive_signals(self, text: str, conversation_id: str) -> CognitiveExtractionPayload:
        """
        Extracts 4-dimensional cognitive memory signals:
        What User Remembers, What User Forgot, Retrieval Actions, and Terminal Outcome.
        Prefers Gemini Free Tier for superior semantic reasoning, with Ollama failover.
        """
        system_instruction = (
            "You are a cognitive memory extraction analyst for Google Photos. "
            "Analyze the user's statement and extract: "
            "1. What the user remembers (entities, spatial setting, temporal cues, visual aesthetics, embedded text). "
            "2. What the user forgot (exact calendar date, exact location, filename, album). "
            "3. Actions attempted (keyword query, face filter, timeline scroll). "
            "4. Terminal outcome (SUCCESS_INSTANT, SUCCESS_EVENTUAL, FAILED_ZERO_RESULTS, FAILED_IRRELEVANT, ABANDONED, EXTERNAL_WORKAROUND). "
            "5. User frustration level from 1 to 5."
        )
        prompt = f"Conversation ID: {conversation_id}\nUser Feedback:\n{text}"
        res = self.run_structured(
            prompt=prompt,
            response_schema=CognitiveExtractionPayload,
            system_instruction=system_instruction,
            prefer_engine="gemini"
        )
        try:
            res["conversation_id"] = conversation_id
            return CognitiveExtractionPayload(**res)
        except Exception as e:
            logger.error(f"Error validating extraction payload: {e}")
            from backend.app.models.schemas import MemorySignals, ForgottenSignals, OutcomeEnum
            return CognitiveExtractionPayload(
                conversation_id=conversation_id,
                memory_signals=MemorySignals(),
                forgotten_signals=ForgottenSignals(),
                actions_taken=[],
                outcome=OutcomeEnum.ABANDONED,
                user_frustration_level=3,
                primary_failure_mode="Extraction parsing error"
            )

    def get_embeddings(self, text: str) -> list[float]:
        """Generates dense vector embeddings using local Ollama (zero cloud cost)."""
        if self.ollama.is_available():
            try:
                emb = self.ollama.get_embeddings(text)
                if emb:
                    return emb
            except Exception:
                pass
        return [0.0] * 768

orchestrator = LLMOrchestrator()
