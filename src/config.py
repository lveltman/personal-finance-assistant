import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Required
TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
MISTRAL_API_KEY: str = os.environ["MISTRAL_API_KEY"]

# LLM
LLM_MODEL: str = os.getenv("LLM_MODEL", "mistral-medium-latest")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
LLM_FALLBACK_MODEL: str = os.getenv("LLM_FALLBACK_MODEL", "gpt-4o-mini")

# Session
SESSION_DIR: Path = Path(os.getenv("SESSION_DIR", "/app/data/sessions"))
SESSION_TTL_DAYS: int = int(os.getenv("SESSION_TTL_DAYS", "7"))
SESSION_SALT: str = os.getenv("SESSION_SALT", "pfa-default-salt")

# Limits
RATE_LIMIT_RPM: int = int(os.getenv("RATE_LIMIT_RPM", "5"))
MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
LLM_MAX_STEPS: int = int(os.getenv("LLM_MAX_STEPS", "10"))
CONVERSATION_HISTORY_LIMIT: int = int(os.getenv("CONVERSATION_HISTORY_LIMIT", "8"))

# Data files
DATA_DIR: Path = Path(os.getenv("DATA_DIR", "/app/data"))
MERCHANT_RULES_PATH: Path = DATA_DIR / "merchant_rules.json"
PRICES_PATH: Path = DATA_DIR / "prices.json"

# Observability
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
