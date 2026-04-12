"""LangGraph tool definitions. Session context is injected via contextvars."""
import contextvars
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from langchain_core.tools import tool
from pydantic import ValidationError

from src import config
from src.core import limit_engine, session as session_store
from src.core.categorizer import batch_categorize, categorize
from src.core.models import ExtractedTransactions, SetLimitParams

log = structlog.get_logger()

# Context vars — set before invoking the agent
_user_hash_var: contextvars.ContextVar[str] = contextvars.ContextVar("user_hash")
_session_var: contextvars.ContextVar[dict] = contextvars.ContextVar("session")
_llm_var: contextvars.ContextVar[Any] = contextvars.ContextVar("llm")


def set_context(user_hash: str, sess: dict, llm: Any = None) -> None:
    _user_hash_var.set(user_hash)
    _session_var.set(sess)
    if llm is not None:
        _llm_var.set(llm)


def _session() -> dict:
    return _session_var.get()


def _save() -> None:
    user_hash = _user_hash_var.get()
    session_store.save_session(user_hash, _session())


# ---------------------------------------------------------------------------


@tool
def load_transactions(period: str) -> str:
    """Load user transactions for analysis.

    Args:
        period: Time period — 'week', 'month', or 'year'
    """
    sess = _session()
    transactions = sess.get("transactions", [])
    if not transactions:
        return "Транзакции не загружены. Попроси пользователя прислать файл .xlsx или .csv с расходами."

    summary = limit_engine.get_spending_summary(transactions, period)
    top = "\n".join(
        f"  • {cat}: {amount:.2f}₽"
        for cat, amount in summary["top_categories"]
    )
    return (
        f"За {period}: {summary['tx_count']} транзакций, итого {summary['total']:.2f}₽\n"
        f"Топ категории:\n{top}"
    )


@tool
def get_spending_report(period: str) -> str:
    """Get detailed spending report for a period.

    Args:
        period: Time period — 'week', 'month', or 'year'
    """
    sess = _session()
    transactions = sess.get("transactions", [])
    if not transactions:
        return "Нет данных о транзакциях."

    summary = limit_engine.get_spending_summary(transactions, period)
    lines = [f"📊 Отчёт за {period} (с {summary['since']}):",
             f"Всего потрачено: {summary['total']:.2f}₽",
             f"Транзакций: {summary['tx_count']}", ""]
    by_cat = sorted(summary["by_category"].items(), key=lambda x: x[1], reverse=True)
    for cat, amount in by_cat:
        lines.append(f"  {cat}: {amount:.2f}₽")
    return "\n".join(lines)


@tool
def set_limit(category: str, amount: float, period: str) -> str:
    """Set a spending limit for a category.

    Args:
        category: Spending category (e.g. 'Кофе', 'Фастфуд')
        amount: Limit amount in rubles
        period: Period — 'week', 'month', or 'year'
    """
    try:
        params = SetLimitParams(category=category, amount=amount, period=period)
    except ValidationError as e:
        return f"❌ Некорректные параметры лимита: {e.errors()[0]['msg']}"
    sess = _session()
    if "limits" not in sess:
        sess["limits"] = {}
    sess["limits"][params.category] = {"amount": params.amount, "period": params.period}
    _save()
    log.info("limit_set", category=params.category, amount=params.amount, period=params.period)
    return f"✅ Лимит установлен: {params.category} — {params.amount:.0f}₽ в {params.period}"


@tool
def list_limits() -> str:
    """List all configured spending limits."""
    sess = _session()
    limits = sess.get("limits", {})
    if not limits:
        return "Лимиты не установлены. Скажи, например: «Установи лимит 500₽ в неделю на кофе»"
    lines = ["📋 Текущие лимиты:"]
    for cat, info in limits.items():
        lines.append(f"  • {cat}: {info['amount']:.0f}₽ / {info['period']}")
    return "\n".join(lines)


@tool
def check_limit_violations() -> str:
    """Check which spending limits have been violated."""
    sess = _session()
    transactions = sess.get("transactions", [])
    limits = sess.get("limits", {})
    if not limits:
        return "Лимиты не установлены."
    if not transactions:
        return "Нет данных о транзакциях."

    violations = limit_engine.check_violations(transactions, limits)
    if not violations:
        return "✅ Все лимиты соблюдены!"
    lines = ["⚠️ Нарушения лимитов:"]
    for v in violations:
        lines.append(
            f"  • {v['category']}: потрачено {v['spent']:.2f}₽, "
            f"лимит {v['limit']:.2f}₽, превышение {v['overage']:.2f}₽ (+{v['overage_pct']}%)"
        )
    return "\n".join(lines)


@tool
def categorize_transaction(merchant: str) -> str:
    """Determine spending category for a merchant name.

    Args:
        merchant: Merchant name as it appears in bank statement
    """
    category, confidence = categorize(merchant)
    return f"Мерчант '{merchant}' → категория '{category}' (уверенность: {confidence:.0%})"


@tool
def find_cheaper(category: str) -> str:
    """Find cheaper alternatives for a spending category.

    Args:
        category: Spending category to find alternatives for
    """
    prices_path = config.PRICES_PATH
    if not prices_path.exists():
        prices_path = Path("data/prices.json")
    if not prices_path.exists():
        return "База цен недоступна."

    with open(prices_path) as f:
        prices_db = json.load(f)

    alternatives = prices_db.get(category, [])
    if not alternatives:
        return f"Альтернативы для категории '{category}' не найдены в базе."

    lines = [f"💰 Дешевле в категории '{category}':"]
    for alt in alternatives[:3]:
        savings = f" (экономия ~{alt['savings_pct']}%)" if alt.get("savings_pct") else ""
        price_str = f" — {alt['price']}₽/{alt['unit']}" if alt.get("price") else ""
        lines.append(f"  • {alt['name']}{price_str}{savings} [{alt.get('where', '')}]")
    lines.append("⚠️ Данные могут быть устаревшими")
    return "\n".join(lines)


@tool
def check_refund(merchant: str) -> str:
    """Check if a refund might be possible for a merchant.

    Args:
        merchant: Merchant name to check refund policy for
    """
    merchant_lower = merchant.lower()
    # Simple rule-based refund policies
    refundable = {
        "ozon": "Возврат в течение 30 дней при наличии чека и товарного вида",
        "wildberries": "Возврат в течение 21 дня, возможен самовывоз",
        "lamoda": "Возврат в течение 365 дней при покупке с примеркой",
        "apple": "Возврат в течение 14 дней при условии ненарушенного вида",
        "mvideo": "Возврат в течение 7 дней (14 для онлайн), при наличии чека",
        "eldorado": "Возврат в течение 14 дней при ненарушенном виде",
    }
    for key, policy in refundable.items():
        if key in merchant_lower:
            return f"✅ {merchant}: {policy}"
    return (
        f"ℹ️ Для '{merchant}' нет стандартных условий возврата в базе.\n"
        f"По закону о защите прав потребителей: товар надлежащего качества "
        f"можно вернуть в течение 14 дней (непродовольственный товар)."
    )


@tool
def save_pending_confirmation(action: str, params: str) -> str:
    """Save an action pending user confirmation (use when confidence < 0.8).

    Args:
        action: Action type, e.g. 'set_limit', 'delete_limit'
        params: JSON string with action parameters
    """
    sess = _session()
    sess["pending_confirmation"] = {"action": action, "params": params}
    _save()
    log.info("pending_confirmation_saved", action=action)
    return f"Действие сохранено для подтверждения: {action} с параметрами {params}"


def _normalize_tx_date(tx: dict, reference: datetime) -> dict:
    """Use dateparser to validate/fix the date returned by LLM."""
    try:
        import dateparser
        parsed = dateparser.parse(
            tx["date"],
            languages=["ru", "en"],
            settings={"RELATIVE_BASE": reference, "RETURN_AS_TIMEZONE_AWARE": False},
        )
        if parsed:
            tx["date"] = parsed.strftime("%Y-%m-%d")
    except Exception:
        pass  # keep whatever LLM returned
    return tx


@tool
def parse_transactions_from_text(text: str) -> str:
    """Parse free-form text into structured transactions and save them to session.

    Use this when the user writes transactions as plain text instead of uploading a file.
    Examples: 'купил кофе 450₽', 'март: starbucks 450, лента 1200, такси 850'.

    Args:
        text: Free-form text containing one or more transactions
    """
    llm = _llm_var.get(None)
    if llm is None:
        return "❌ LLM недоступен для извлечения транзакций."

    now = datetime.utcnow()
    today = now.strftime("%Y-%m-%d")

    extraction_prompt = f"""Сегодня {today}. Используй эту дату как точку отсчёта для всех относительных дат.

Извлеки транзакции из текста пользователя в структурированный JSON.

Текст: {text}

Верни JSON строго в формате:
{{
  "transactions": [
    {{"date": "YYYY-MM-DD", "amount": 123.0, "merchant": "название", "category": ""}}
  ],
  "note": "необязательное пояснение если что-то неясно"
}}

Правила:
- date: вычисли точную дату ISO 8601 от сегодня ({today}). Примеры: "вчера"=вчерашняя дата, "три дня назад"=сегодня минус 3 дня, "в прошлую пятницу"=дата прошлой пятницы. Форматы дат: "2026-03-05", "2026 03 05", "05.03.2026", "5 марта" — все корректны
- Если дата не указана — используй сегодня ({today})
- Если один временной контекст для нескольких трат ("вчера купила X, Y и Z") — все транзакции получают ОДИНАКОВУЮ дату
- amount: только число, всегда положительное
- merchant: ЛЮБОЙ текст между датой и суммой — это merchant. Даже если слово похоже на описание или тег — всё равно запиши его в merchant. НИКОГДА не оставляй merchant пустым, если в строке есть хоть какое-то слово
- category: оставь пустым

Примеры:
- "Starbucks 450" → date={today}, merchant="Starbucks", amount=450
- "2026-03-05 Пятёрочка 1200" → date="2026-03-05", merchant="Пятёрочка", amount=1200
- "2026 03 05 BezSummy 500" → date="2026-03-05", merchant="BezSummy", amount=500
- "вчера такси 850 и кофе 200" → две транзакции с датой вчера"""

    try:
        extractor = llm.with_structured_output(ExtractedTransactions)
        result: ExtractedTransactions = extractor.invoke(extraction_prompt)
    except Exception:
        # Fallback: plain LLM call + manual JSON parse
        try:
            from langchain_core.messages import HumanMessage
            raw = llm.invoke([HumanMessage(content=extraction_prompt)])
            import re
            json_match = re.search(r"\{.*\}", raw.content, re.DOTALL)
            if not json_match:
                return "❌ Не удалось распознать транзакции из текста. Попробуй загрузить файл .xlsx или .csv"
            data = json.loads(json_match.group())
            result = ExtractedTransactions.model_validate(data)
        except Exception as e:
            log.error("text_extraction_failed", error=str(e))
            return "❌ Не удалось распознать транзакции из текста. Попробуй загрузить файл .xlsx или .csv"

    if not result.transactions:
        return "❌ В тексте не найдено транзакций. Попробуй написать например: «кофе 450₽, такси 850₽»"

    # Normalize dates with dateparser as safety net after LLM extraction
    tx_dicts = [_normalize_tx_date(tx.model_dump(), now) for tx in result.transactions]
    tx_dicts = batch_categorize(tx_dicts, llm=llm)

    sess = _session()
    existing = sess.get("transactions", [])
    sess["transactions"] = existing + tx_dicts
    sess["last_file_ts"] = datetime.utcnow().isoformat()
    _save()

    log.info("transactions_parsed_from_text", count=len(tx_dicts))

    all_transactions = sess.get("transactions", [])
    summary = limit_engine.get_spending_summary(all_transactions, "month")
    by_cat = sorted(summary["by_category"].items(), key=lambda x: x[1], reverse=True)
    top = "\n".join(f"  • {cat}: {amount:.0f}₽" for cat, amount in by_cat[:5])

    lines = [f"✅ Добавлено {len(tx_dicts)} транзакций:"]
    for tx in tx_dicts:
        lines.append(f"  • {tx['date']} | {tx['merchant']} | {tx['amount']:.0f}₽ | {tx['category']}")
    if result.note:
        lines.append(f"\nℹ️ {result.note}")
    lines.append(f"\n📊 Расходы за месяц (всего): {summary['total']:.0f}₽")
    lines.append(f"По категориям:\n{top}")
    lines.append("\n[ИНСТРУКЦИЯ ДЛЯ АГЕНТА: числа выше взяты из инструмента, используй их как есть — не пересчитывай]")
    return "\n".join(lines)


@tool
def recategorize_all_transactions() -> str:
    """Re-run categorization for all transactions in session and save results.

    Use this when categories are missing, show as 'nan', 'Прочее', or need to be refreshed.
    Updates the session so future reports show correct categories.
    """
    sess = _session()
    transactions = sess.get("transactions", [])
    if not transactions:
        return "Нет транзакций для категоризации."

    uncategorized_before = sum(1 for tx in transactions if not tx.get("category") or tx.get("category") in ("", "Прочее", "nan"))
    llm = _llm_var.get(None)
    updated = batch_categorize(transactions, llm=llm)
    sess["transactions"] = updated
    _save()

    uncategorized_after = sum(1 for tx in updated if tx.get("category") in ("Прочее", ""))
    categorized = len(updated) - uncategorized_after

    from collections import Counter
    counts = Counter(tx.get("category", "Прочее") for tx in updated)
    top = "\n".join(f"  • {cat}: {n} транзакций" for cat, n in counts.most_common(5))

    log.info("recategorized", total=len(updated), categorized=categorized)
    return (
        f"✅ Категоризация обновлена для {len(updated)} транзакций\n"
        f"Было без категории: {uncategorized_before} → стало: {uncategorized_after}\n\n"
        f"Топ категории:\n{top}"
    )


@tool
def generate_refund_letter(
    merchant: str,
    product: str,
    amount: float,
    purchase_date: str,
    reason: str = "товар не подошёл",
) -> str:
    """Generate a ready-to-send refund request letter.

    Use when the user wants to return a purchase and needs a formal letter.

    Args:
        merchant: Store or brand name (e.g. 'NYX', 'Ozon')
        product: Product name and description (e.g. 'тональный крем NYX Stay Matte')
        amount: Purchase amount in rubles
        purchase_date: Purchase date in any format (e.g. '2026-03-15' or '15 марта')
        reason: Reason for return (default: 'товар не подошёл')
    """
    llm = _llm_var.get(None)
    if llm is None:
        return _refund_letter_template(merchant, product, amount, purchase_date, reason)

    prompt = f"""Составь официальное заявление на возврат товара.
Используй деловой стиль. Верни ТОЛЬКО текст заявления, без пояснений.

Данные:
- Магазин/бренд: {merchant}
- Товар: {product}
- Сумма: {amount:.0f}₽
- Дата покупки: {purchase_date}
- Причина возврата: {reason}

Структура заявления:
1. Шапка: Кому (директору/в службу поддержки {merchant}), От кого (Покупатель — оставь поле [ФИО])
2. Заголовок: «Заявление о возврате товара»
3. Тело: суть обращения с датой, товаром, суммой, причиной и ссылкой на закон о ЗПП (ст. 25)
4. Требование: вернуть денежные средства в размере {amount:.0f}₽
5. Дата и подпись: [Дата], [Подпись / ФИО]"""

    try:
        from langchain_core.messages import HumanMessage
        response = llm.invoke([HumanMessage(content=prompt)])
        letter = response.content.strip()
    except Exception as e:
        log.warning("refund_letter_llm_failed", error=str(e))
        letter = _refund_letter_template(merchant, product, amount, purchase_date, reason)

    return f"📄 Заявление на возврат:\n\n{letter}\n\n---\n💡 Заполни поля [ФИО] и [Дата] перед отправкой."


def _refund_letter_template(
    merchant: str, product: str, amount: float, purchase_date: str, reason: str
) -> str:
    """Fallback template if LLM is unavailable."""
    return f"""Директору / В службу поддержки {merchant}
От: [ФИО покупателя]

ЗАЯВЛЕНИЕ О ВОЗВРАТЕ ТОВАРА

Прошу принять возврат товара и вернуть уплаченные денежные средства.

Товар: {product}
Дата покупки: {purchase_date}
Сумма: {amount:.0f}₽
Причина возврата: {reason}

На основании ст. 25 Закона РФ «О защите прав потребителей» прошу вернуть денежные средства в размере {amount:.0f} ({"".join([str(int(amount))])}) рублей в течение 10 дней с момента получения данного заявления.

[Дата]
[Подпись / ФИО]"""


ALL_TOOLS = [
    load_transactions,
    get_spending_report,
    set_limit,
    list_limits,
    check_limit_violations,
    categorize_transaction,
    recategorize_all_transactions,
    find_cheaper,
    check_refund,
    generate_refund_letter,
    save_pending_confirmation,
    parse_transactions_from_text,
]
