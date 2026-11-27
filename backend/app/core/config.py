"""Application configuration, loaded from environment variables (.env supported)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent

# Load the project-level .env first, then a backend-level one (backend wins).
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env", override=True)


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class Settings:
    def __init__(self) -> None:
        self.app_name = "MediMemory API"
        self.environment = os.getenv("ENVIRONMENT", "development")

        # Database: SQLite by default, PostgreSQL via DATABASE_URL.
        default_db = f"sqlite:///{(BACKEND_DIR / 'medimemory.db').as_posix()}"
        db_url = (os.getenv("DATABASE_URL") or default_db).strip()
        # Accept the URLs Render/Heroku-style providers hand out and use the installed psycopg (v3) driver.
        for prefix in ("postgres://", "postgresql://"):
            if db_url.startswith(prefix):
                db_url = "postgresql+psycopg://" + db_url[len(prefix):]
        self.database_url = db_url
        # Create tables and load demo data at startup (so a plain "uvicorn app.main:app" start command works).
        self.auto_init_db = _bool("AUTO_INIT_DB", True)
        self.seed_demo = _bool("SEED_DEMO", True)

        # Auth
        self.jwt_secret = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY") or "dev-only-change-me-please-0123456789abcdef"
        self.jwt_algorithm = "HS256"
        self.access_token_minutes = _int("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 12)

        # CORS
        origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        self.cors_origins = [o.strip().rstrip("/") for o in origins.split(",") if o.strip()]
        # Also allow Vercel / Render hosted frontends (auth uses bearer tokens, not cookies). Set to "" to disable.
        self.cors_origin_regex = os.getenv("CORS_ORIGIN_REGEX", r"https://([a-z0-9-]+\.)*(vercel\.app|onrender\.com)")

        # File storage
        self.storage_dir = Path(os.getenv("STORAGE_DIR") or (BACKEND_DIR / "storage"))
        self.max_upload_mb = _int("MAX_UPLOAD_MB", 10)

        # LLM (any OpenAI-compatible endpoint)
        self.llm_api_key = (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        self.llm_base_url = (os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.llm_model = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        self.embedding_provider = os.getenv("EMBEDDING_PROVIDER", "local").lower()  # local | openai
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

        # ElevenLabs
        self.elevenlabs_api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
        self.elevenlabs_base_url = (os.getenv("ELEVENLABS_BASE_URL") or "https://api.elevenlabs.io").rstrip("/")
        self.elevenlabs_stt_model = os.getenv("ELEVENLABS_STT_MODEL") or "scribe_v1"
        self.elevenlabs_tts_model = os.getenv("ELEVENLABS_TTS_MODEL") or os.getenv("ELEVENLABS_MODEL_ID") or "eleven_multilingual_v2"
        # Default voice: "Rachel" premade voice id. Override in .env or per user in Settings.
        self.elevenlabs_voice_id = (os.getenv("ELEVENLABS_VOICE_ID") or "21m00Tcm4TlvDq8ikWAM").strip()
        # Optional separate voice for Tamil playback (pick one in the ElevenLabs Voice Library that sounds natural in Tamil).
        self.elevenlabs_voice_id_ta = (os.getenv("ELEVENLABS_VOICE_ID_TA") or "").strip()

        # OCR
        self.tesseract_cmd = os.getenv("TESSERACT_CMD", "")

        # RAG
        self.rag_top_k = _int("RAG_TOP_K", 5)
        self.rag_min_score = float(os.getenv("RAG_MIN_SCORE", "0.12"))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def elevenlabs_enabled(self) -> bool:
        return bool(self.elevenlabs_api_key)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
