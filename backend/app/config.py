"""All settings come from environment variables (see ../.env.example)."""
import os
import secrets
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "uploads").mkdir(exist_ok=True)

DB_PATH = os.getenv("DB_PATH", str(DATA_DIR / "rag.db"))


def _jwt_secret() -> str:
    env = os.getenv("JWT_SECRET")
    if env:
        return env
    f = DATA_DIR / ".jwt_secret"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(48))
    return f.read_text().strip()


JWT_SECRET = _jwt_secret()
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "30"))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "7"))

# LLM: "anthropic" | "openai" | "mock". Auto-picks from available keys when empty.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "").lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")

# Embeddings: "hash" (offline, default) | "st" (sentence-transformers) | "openai"
EMBEDDER = os.getenv("EMBEDDER", "hash").lower()
ST_MODEL = os.getenv("ST_MODEL", "all-MiniLM-L6-v2")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# Chunking / retrieval
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))
TOP_K = int(os.getenv("TOP_K", "5"))
MIN_EVIDENCE_SCORE = float(os.getenv("MIN_EVIDENCE_SCORE", "0.2"))

# Conversation memory
HISTORY_WINDOW = int(os.getenv("HISTORY_WINDOW", "6"))  # recent messages sent verbatim
SUMMARY_TRIGGER = int(os.getenv("SUMMARY_TRIGGER", "12"))  # summarize when older msgs exceed this

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
ALLOWED_EXT = {".pdf", ".docx", ".html", ".htm", ".md", ".markdown", ".txt"}
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:8001").split(",")
