"""Application configuration. Reads .env once at import time."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_MODEL = "gpt-4o-mini"
DB_PATH = PROJECT_ROOT / "data" / "meetings.db"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 2
MAX_PASSES = 2          # one corrective extraction pass at most, then escalate


def get_api_key() -> str | None:
    """Return the OpenAI key, or None if unset. Never log the return value."""
    return os.environ.get("OPENAI_API_KEY")
