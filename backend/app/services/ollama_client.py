import requests
import json
import re
from typing import Optional, Dict, Any, List
from backend.app.core.config import settings

class OllamaClient:
    def __init__(self, base_url: Optional[str] = None, default_model: Optional[str] = None):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.default_model = default_model or settings.OLLAMA_MODEL
        self.embed_model = settings.OLLAMA_EMBED_MODEL
        self._embeddings_supported: Optional[bool] = None

    def is_available(self) -> bool:
        """Check if local Ollama daemon is running."""
        try:
            res = requests.get(f"{self.base_url}/api/tags", timeout=2.0)
            return res.status_code == 200
        except Exception:
            return False

    def get_installed_models(self) -> List[str]:
        try:
            res = requests.get(f"{self.base_url}/api/tags", timeout=3.0)
            if res.status_code == 200:
                data = res.json()
                return [m.get("name") for m in data.get("models", [])]
            return []
        except Exception:
            return []

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        num_predict: Optional[int] = None,
        timeout: float = 60.0
    ) -> str:
        """
        Calls Ollama /api/generate endpoint.
        Returns raw text response from Ollama.
        """
        target_model = model or self.default_model
        options = {
            "temperature": temperature
        }
        if num_predict is not None:
            options["num_predict"] = num_predict
        payload = {
            "model": target_model,
            "prompt": prompt,
            "stream": False,
            "options": options
        }
        if system_prompt:
            payload["system"] = system_prompt
        if json_mode:
            payload["format"] = "json"

        res = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=timeout)
        res.raise_for_status()
        data = res.json()
        return data.get("response", "")

    def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
        num_predict: Optional[int] = 120
    ) -> Dict[str, Any]:
        """
        Calls Ollama and extracts clean JSON, mitigating markdown formatting
        or preamble strings (Edge Case 4.2 in edge-case.md).
        """
        raw_text = self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            json_mode=True,
            temperature=temperature,
            num_predict=num_predict
        )
        
        # Try direct parse
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        # Regex isolation of outermost {...}
        match = re.search(r'(\{.*\})', raw_text, re.DOTALL)
        if match:
            clean_str = match.group(1)
            try:
                return json.loads(clean_str)
            except json.JSONDecodeError:
                pass

        # Return empty dict if unparseable
        return {"error": "Failed to parse JSON from Ollama", "raw_response": raw_text}

    def get_embeddings(self, text: str, model: Optional[str] = None) -> List[float]:
        """Calls Ollama /api/embeddings endpoint safely, caching failure if not supported."""
        if self._embeddings_supported is False:
            return []

        target_model = model or self.embed_model
        payload = {
            "model": target_model,
            "prompt": text
        }
        try:
            res = requests.post(f"{self.base_url}/api/embeddings", json=payload, timeout=5.0)
            if res.status_code == 200:
                self._embeddings_supported = True
                data = res.json()
                return data.get("embedding", [])
            else:
                self._embeddings_supported = False
                return []
        except Exception:
            self._embeddings_supported = False
            return []

ollama_client = OllamaClient()
