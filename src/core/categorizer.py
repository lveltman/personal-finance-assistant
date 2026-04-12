"""3-level categorization: keyword rules → LLM fallback."""
import json
from functools import lru_cache
from pathlib import Path

import structlog

from src import config

log = structlog.get_logger()

KNOWN_CATEGORIES = [
    "Кофе", "Фастфуд", "Рестораны", "Продукты", "Такси", "Аптека",
    "Подписки", "Маркетплейсы", "Одежда", "Дом", "Развлечения",
    "Спорт", "Электроника", "Топливо", "Связь", "Банк",
    "Транспорт", "Автоуслуги", "Красота", "Здоровье", "Животные",
    "Подарки", "ЖКХ", "Образование", "Путешествия", "Прочее",
]

@lru_cache(maxsize=1)  # cache cleared on container restart
def _load_rules() -> dict[str, str]:
    path = config.MERCHANT_RULES_PATH
    if not path.exists():
        # Try relative path for local dev
        path = Path("data/merchant_rules.json")
    if not path.exists():
        log.warning("merchant_rules_not_found")
        return {}
    with open(path) as f:
        return json.load(f)


def categorize_by_rules(merchant: str) -> tuple[str | None, float]:
    """Level 1: deterministic keyword lookup. Returns (category, confidence)."""
    rules = _load_rules()
    merchant_lower = merchant.lower().strip()
    # Exact match
    if merchant_lower in rules:
        return rules[merchant_lower], 1.0
    # Substring match
    for keyword, category in rules.items():
        if keyword in merchant_lower or merchant_lower in keyword:
            return category, 0.9
    return None, 0.0


def categorize(merchant: str, llm=None) -> tuple[str, float]:
    """
    Categorize a merchant using available methods.
    Returns (category, confidence).
    """
    # Level 1: keyword rules
    category, confidence = categorize_by_rules(merchant)
    if category:
        log.debug("categorized_by_rules", merchant=merchant, category=category)
        return category, confidence

    # Level 2: LLM fallback (if LLM available)
    if llm is not None:
        try:
            category, confidence = _categorize_by_llm(merchant, llm)
            if category:
                log.debug("categorized_by_llm", merchant=merchant, category=category)
                return category, confidence
        except Exception as e:
            log.warning("llm_categorize_failed", merchant=merchant, error=str(e))

    return "Прочее", 0.5


def _categorize_by_llm(merchant: str, llm) -> tuple[str, float]:
    """Level 2: single LLM call to categorize."""
    categories_str = ", ".join(KNOWN_CATEGORIES)
    prompt = (
        f"Определи категорию расхода для мерчанта: \"{merchant}\"\n"
        f"Доступные категории: {categories_str}\n"
        f"Ответь ТОЛЬКО одним словом — названием категории из списка. "
        f"Если не подходит ни одна — ответь 'Прочее'."
    )
    from langchain_core.messages import HumanMessage
    response = llm.invoke([HumanMessage(content=prompt)])
    text = response.content.strip()
    # Find matching category
    for cat in KNOWN_CATEGORIES:
        if cat.lower() in text.lower():
            return cat, 0.8
    return "Прочее", 0.5


def batch_categorize(transactions: list[dict], llm=None) -> list[dict]:
    """Add/fill category field for all transactions."""
    result = []
    for tx in transactions:
        if not tx.get("category"):
            category, _ = categorize(tx["merchant"], llm)
            tx = {**tx, "category": category}
        result.append(tx)
    return result
