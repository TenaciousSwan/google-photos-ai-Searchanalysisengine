import json
import re
from typing import Optional, Dict, Any, Type
from pydantic import BaseModel
from backend.app.core.config import settings

class RateLimitException(Exception):
    """Raised when Gemini Free Tier quota or rate limit is reached (HTTP 429)."""
    pass

class GeminiClient:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_MODEL
        self._client = None
        if self.api_key:
            self._init_sdk()

    def _init_sdk(self):
        try:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        except Exception:
            self._client = None

    def is_available(self) -> bool:
        """Returns True if Gemini API key is configured."""
        return bool(self.api_key and self.api_key.strip() and self.api_key != "your_gemini_api_key_here")

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.2
    ) -> str:
        """Generate text from Gemini with rate limit detection."""
        if not self.is_available():
            raise ValueError("Gemini API key is not configured or invalid.")

        target_model = model or self.model_name
        try:
            if not self._client:
                self._init_sdk()
                if not self._client:
                    raise RuntimeError("Could not initialize google.genai Client")

            config = {
                "temperature": temperature,
            }
            if system_instruction:
                config["system_instruction"] = system_instruction

            response = self._client.models.generate_content(
                model=target_model,
                contents=prompt,
                config=config
            )
            return response.text or ""
        except Exception as e:
            err_msg = str(e).lower()
            if "429" in err_msg or "resource_exhausted" in err_msg or "quota" in err_msg:
                raise RateLimitException(f"Gemini quota exhausted: {e}") from e
            raise

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[BaseModel],
        system_instruction: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1
    ) -> Dict[str, Any]:
        """Generate structured JSON adhering to a Pydantic schema using Gemini."""
        if not self.is_available():
            raise ValueError("Gemini API key is not configured.")

        target_model = model or self.model_name
        try:
            if not self._client:
                self._init_sdk()

            config = {
                "temperature": temperature,
                "response_mime_type": "application/json",
                "response_schema": response_schema
            }
            if system_instruction:
                config["system_instruction"] = system_instruction

            response = self._client.models.generate_content(
                model=target_model,
                contents=prompt,
                config=config
            )
            raw_text = response.text or "{}"
            return json.loads(raw_text)
        except Exception as e:
            err_msg = str(e).lower()
            if "429" in err_msg or "resource_exhausted" in err_msg or "quota" in err_msg:
                raise RateLimitException(f"Gemini quota exhausted: {e}") from e
            raise

gemini_client = GeminiClient()
