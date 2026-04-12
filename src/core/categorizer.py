"""3-level categorization: keyword rules → embedding similarity → LLM fallback."""
import json
from functools import lru_cache
from pathlib import Path

import structlog

from src import config, metrics

log = structlog.get_logger()

KNOWN_CATEGORIES = [
    "Кофе", "Фастфуд", "Рестораны", "Продукты", "Такси", "Аптека",
    "Подписки", "Маркетплейсы", "Одежда", "Дом", "Развлечения",
    "Спорт", "Электроника", "Топливо", "Связь", "Банк",
    "Транспорт", "Автоуслуги", "Красота", "Здоровье", "Животные",
    "Подарки", "ЖКХ", "Образование", "Путешествия", "Прочее",
]

# Rich keyword descriptions improve embedding accuracy per category
CATEGORY_DESCRIPTIONS = {
    "Кофе": "кофе кофейня starbucks cofix coffee латте капучино americano espresso",
    "Фастфуд": "фастфуд mcdonalds kfc burger king макдоналдс бургер fast food чебуречная",
    "Рестораны": "ресторан кафе суши роллы пицца столовая обед ужин bistro sushi",
    "Продукты": "продукты супермаркет лента перекрёсток пятёрочка магнит ашан grocery",
    "Такси": "такси uber lyft яндекс такси ситимобил bolt ride sharing каршеринг",
    "Аптека": "аптека pharmacy лекарства здоровье медицина витамины таблетки",
    "Подписки": "подписка netflix spotify apple music youtube premium streaming subscription",
    "Маркетплейсы": "маркетплейс ozon wildberries amazon aliexpress lamoda онлайн покупки",
    "Одежда": "одежда zara h&m fashion магазин обувь accessory бутик adidas nike",
    "Дом": "дом мебель ikea хозяйство ремонт строительство leroy merlin lerua",
    "Развлечения": "кино театр игры game cinema entertainment боулинг квест батут",
    "Спорт": "спорт фитнес зал тренажёр бассейн йога world class gym crossfit",
    "Электроника": "электроника гаджеты телефон ноутбук м.видео eldorado apple store dns",
    "Топливо": "топливо бензин заправка азс газпром лукойл shell petrol",
    "Связь": "связь телефон интернет мобильный билайн мегафон мтс tele2 ростелеком",
    "Банк": "банк комиссия перевод снятие наличных atm cash fee обслуживание",
    "Транспорт": "транспорт метро автобус трамвай электричка проездной билет",
    "Автоуслуги": "автомойка шиномонтаж парковка штраф гибдд автосервис техосмотр",
    "Красота": "красота салон парикмахерская маникюр косметика beauty spa массаж",
    "Здоровье": "здоровье клиника врач анализы стоматолог медцентр лечение",
    "Животные": "животные зоомагазин ветеринар корм для животных питомец",
    "Подарки": "подарки цветы праздник сувенир цветочный магазин букет",
    "ЖКХ": "жкх коммунальные услуги квартплата электричество газ вода",
    "Образование": "образование курсы учёба университет книги онлайн курсы",
    "Путешествия": "путешествия отель авиабилеты booking airbnb турагентство",
    "Прочее": "прочее разное other miscellaneous",
}

_EMBEDDING_THRESHOLD = 0.40  # cosine similarity threshold

# Module-level cache (loaded once per process)
_embedding_model = None
_category_embeddings = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            log.info("embedding_model_loaded")
        except Exception as e:
            log.warning("embedding_model_unavailable", error=str(e))
            _embedding_model = False  # avoid retrying on every call
    return _embedding_model if _embedding_model is not False else None


def _get_category_embeddings():
    global _category_embeddings
    if _category_embeddings is None:
        model = _get_embedding_model()
        if model is None:
            return None
        descriptions = [CATEGORY_DESCRIPTIONS.get(cat, cat) for cat in KNOWN_CATEGORIES]
        _category_embeddings = model.encode(descriptions, normalize_embeddings=True)
        log.info("category_embeddings_built", categories=len(KNOWN_CATEGORIES))
    return _category_embeddings


@lru_cache(maxsize=1)  # cache cleared on container restart
def _load_rules() -> dict[str, str]:
    path = config.MERCHANT_RULES_PATH
    if not path.exists():
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
    if merchant_lower in rules:
        return rules[merchant_lower], 1.0
    for keyword, category in rules.items():
        if keyword in merchant_lower or merchant_lower in keyword:
            return category, 0.9
    return None, 0.0


def categorize_by_embedding(merchant: str) -> tuple[str | None, float]:
    """Level 2: cosine similarity against category description embeddings."""
    try:
        import numpy as np
        model = _get_embedding_model()
        embeddings = _get_category_embeddings()
        if model is None or embeddings is None:
            return None, 0.0
        merchant_emb = model.encode([merchant.lower()], normalize_embeddings=True)[0]
        similarities = embeddings @ merchant_emb
        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])
        if best_score >= _EMBEDDING_THRESHOLD:
            return KNOWN_CATEGORIES[best_idx], round(best_score, 3)
        return None, round(best_score, 3)
    except Exception as e:
        log.warning("embedding_categorize_failed", error=str(e))
        return None, 0.0


def categorize(merchant: str, llm=None) -> tuple[str, float]:
    """
    3-level categorization cascade.
    Returns (category, confidence).
    """
    # Level 1: keyword rules (< 1ms)
    category, confidence = categorize_by_rules(merchant)
    if category:
        log.debug("categorized_by_rules", merchant=merchant, category=category)
        metrics.categorization_total.labels(method="rules").inc()
        return category, confidence

    # Level 2: embedding similarity (< 50ms, no API call)
    category, confidence = categorize_by_embedding(merchant)
    if category:
        log.debug("categorized_by_embedding", merchant=merchant, category=category, score=confidence)
        metrics.categorization_total.labels(method="embedding").inc()
        return category, confidence

    # Level 3: LLM fallback
    if llm is not None:
        try:
            category, confidence = _categorize_by_llm(merchant, llm)
            if category:
                log.debug("categorized_by_llm", merchant=merchant, category=category)
                metrics.categorization_total.labels(method="llm").inc()
                return category, confidence
        except Exception as e:
            log.warning("llm_categorize_failed", merchant=merchant, error=str(e))

    metrics.categorization_total.labels(method="fallback").inc()
    return "Прочее", 0.5


def _categorize_by_llm(merchant: str, llm) -> tuple[str, float]:
    """Level 3: single LLM call to categorize."""
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
