"""Pydantic models — shared data contracts across the codebase."""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


def _coerce_amount(v: Any) -> float:
    """Accept '500₽', '1 000,50', 1000 — always returns float."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        cleaned = re.sub(r"[₽$€\s\xa0]", "", v).replace(",", ".")
        return float(cleaned)
    raise ValueError(f"Cannot convert {v!r} to amount")


FlexibleAmount = Annotated[float, Field(gt=0)]


class Transaction(BaseModel):
    date: str
    amount: float = Field(ge=0)
    merchant: str
    category: str = ""

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, v: Any) -> float:
        return _coerce_amount(v)


class SpendingLimit(BaseModel):
    amount: float = Field(gt=0, description="Limit amount in rubles")
    period: Literal["week", "month", "year"]

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, v: Any) -> float:
        return _coerce_amount(v)

    @field_validator("period", mode="before")
    @classmethod
    def normalize_period(cls, v: Any) -> str:
        """Accept 'неделя', 'месяц', 'год' alongside English."""
        mapping = {
            "неделя": "week", "неделю": "week", "week": "week",
            "месяц": "month", "month": "month",
            "год": "year", "year": "year",
        }
        normalized = mapping.get(str(v).lower().strip())
        if not normalized:
            raise ValueError(f"Unknown period '{v}'. Use: week, month, year")
        return normalized


class SetLimitParams(BaseModel):
    category: str = Field(min_length=1)
    amount: float = Field(gt=0)
    period: Literal["week", "month", "year"]

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, v: Any) -> float:
        return _coerce_amount(v)

    @field_validator("period", mode="before")
    @classmethod
    def normalize_period(cls, v: Any) -> str:
        mapping = {
            "неделя": "week", "неделю": "week", "week": "week",
            "месяц": "month", "month": "month",
            "год": "year", "year": "year",
        }
        normalized = mapping.get(str(v).lower().strip())
        if not normalized:
            raise ValueError(f"Unknown period '{v}'. Use: week, month, year")
        return normalized


class PendingConfirmation(BaseModel):
    action: str
    params: str  # JSON string


class ExtractedTransactions(BaseModel):
    """Structured output from free-text transaction extraction."""
    transactions: list[Transaction]
    note: Optional[str] = None  # LLM can add a clarification note


class SessionState(BaseModel):
    user_id_hash: str
    transactions: list[Transaction] = []
    limits: dict[str, SpendingLimit] = {}
    last_file_ts: Optional[str] = None
    conversation_history: list[dict] = []
    pending_confirmation: Optional[PendingConfirmation] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
