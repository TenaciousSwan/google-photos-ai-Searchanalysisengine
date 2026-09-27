import os
from pathlib import Path
from pydantic import BaseModel

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_FIXTURES_DIR = DATA_DIR / "raw_fixtures"
FRONTEND_DIR = BASE_DIR / "frontend"

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)

class Settings(BaseModel):
    PROJECT_NAME: str = "Google Photos AI Discovery Engine"
    VERSION: str = "0.1.0"
    DEBUG: bool = os.getenv("DEBUG", "True").lower() in ("true", "1")
    
    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = DATA_DIR
    RAW_FIXTURES_DIR: Path = RAW_FIXTURES_DIR
    FRONTEND_DIR: Path = FRONTEND_DIR

    # Database
    DB_PATH: Path = DATA_DIR / "discovery.db"
    
    # Gemini Free Tier Configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    GEMINI_RPM_LIMIT: int = int(os.getenv("GEMINI_RPM_LIMIT", "14"))
    
    # Ollama Configuration
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
    OLLAMA_EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "qwen2.5:1.5b")

settings = Settings()
