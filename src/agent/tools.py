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


ALL_TOOLS = [
    load_transactions,
    get_spending_report,
    set_limit,
    list_limits,
    check_limit_violations,
    categorize_transaction,
    find_cheaper,
    check_refund,
    save_pending_confirmation,
]
