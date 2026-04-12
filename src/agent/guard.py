"""Pre-flight guard: rate limit, domain check, PII masking."""
import re
import time
from collections import defaultdict
from enum import Enum

import structlog
from pydantic import BaseModel

from src import config

log = structlog.get_logger()

# In-memory rate limit store: user_hash → list of request timestamps
_rate_store: dict[str, list[float]] = defaultdict(list)

FINANCE_KEYWORDS = [
    "трат", "расход", "лимит", "бюджет", "деньг", "рубл", "купил", "купи",
    "потратил", "потрат", "баланс", "кофе", "еда", "магазин", "такси",
    "отчёт", "отчет", "превышен", "анализ", "файл", "xlsx", "csv",
    "категор", "merchant", "транзакц", "spend", "limit", "budget",
    "report", "дешевл", "возврат", "сколько", "покажи", "установи",
    "убери", "удали", "неделю", "месяц", "год",
]

# PII patterns
_EMAIL_RE = re.compile(r"\b[\w.+\-]+@[\w\-]+\.[\w.]+\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")
_CARD_RE = re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b")
_ADDRESS_RE = re.compile(r"\b(ул\.|улица|пр\.|проспект|д\.|дом)\s+[\w\s\d.,]+", re.IGNORECASE)


class RefusalReason(str, Enum):
    RATE_LIMIT = "rate_limit"
    OUT_OF_DOMAIN = "out_of_domain"
    FILE_TOO_LARGE = "file_too_large"


class GuardRefusalDetail(BaseModel):
    reason: RefusalReason
    message: str
    user_hash: str = ""


class GuardRefusal(Exception):
    """Raised when a request should be refused without calling the LLM."""

    def __init__(self, reason: RefusalReason, message: str, user_hash: str = "") -> None:
        self.detail = GuardRefusalDetail(reason=reason, message=message, user_hash=user_hash)
        super().__init__(message)

    def __str__(self) -> str:
        return self.detail.message


def check_rate_limit(user_hash: str) -> None:
    now = time.time()
    window = 60.0
    _rate_store[user_hash] = [t for t in _rate_store[user_hash] if now - t < window]
    if len(_rate_store[user_hash]) >= config.RATE_LIMIT_RPM:
        raise GuardRefusal(
            reason=RefusalReason.RATE_LIMIT,
            message=f"⏱ Слишком много запросов. Подожди немного — разрешено {config.RATE_LIMIT_RPM} запросов в минуту.",
            user_hash=user_hash,
        )
    _rate_store[user_hash].append(now)


def check_domain(text: str, user_hash: str = "") -> None:
    """Refuse clearly off-topic requests without calling LLM."""
    if not text or len(text.strip()) < 3:
        return
    text_lower = text.lower()
    if any(kw in text_lower for kw in FINANCE_KEYWORDS):
        return
    if len(text.strip().split()) <= 5:
        return
    if len(text.strip().split()) > 15:
        raise GuardRefusal(
            reason=RefusalReason.OUT_OF_DOMAIN,
            message=(
                "🤖 Я специализируюсь только на анализе личных финансов.\n"
                "Пришли мне файл с транзакциями (.xlsx/.csv) или задай вопрос про расходы и лимиты."
            ),
            user_hash=user_hash,
        )


def mask_pii(text: str) -> str:
    """Mask PII before sending to LLM."""
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    text = _CARD_RE.sub("[CARD]", text)
    text = _ADDRESS_RE.sub("[LOC]", text)
    return text


def run_preflight(user_hash: str, text: str) -> str:
    """Run all pre-flight checks. Returns sanitized text or raises GuardRefusal."""
    check_rate_limit(user_hash)
    check_domain(text, user_hash)
    sanitized = mask_pii(text)
    log.debug("preflight_passed", user_hash=user_hash)
    return sanitized
