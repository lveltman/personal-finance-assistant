"""System prompt builder."""
from datetime import datetime


def build_system_prompt(session: dict) -> str:
    transactions = session.get("transactions", [])
    limits = session.get("limits", {})
    last_file_ts = session.get("last_file_ts")
    tx_count = len(transactions)

    # Build data summary (aggregates only, no raw data)
    if transactions:
        from src.core.limit_engine import get_spending_summary
        summary = get_spending_summary(transactions, "month")
        top_cats = ", ".join(
            f"{cat}: {amount:.0f}₽" for cat, amount in summary["top_categories"]
        )
        data_context = (
            f"- Транзакций загружено: {tx_count}\n"
            f"- Последний файл: {last_file_ts or 'неизвестно'}\n"
            f"- Расходы за месяц: {summary['total']:.0f}₽\n"
            f"- Топ категории: {top_cats}\n"
        )
    else:
        data_context = "- Транзакции не загружены. Попроси пользователя прислать файл .xlsx или .csv\n"

    if limits:
        limits_context = "- Лимиты: " + ", ".join(
            f"{cat} {info['amount']}₽/{info['period']}"
            for cat, info in limits.items()
        ) + "\n"
    else:
        limits_context = "- Лимиты не установлены\n"

    return f"""Ты — персональный финансовый ассистент. Анализируешь расходы пользователя, отслеживаешь лимиты, находишь возможности для экономии.

ДАННЫЕ ПОЛЬЗОВАТЕЛЯ (сейчас {datetime.utcnow().strftime('%Y-%m-%d')}):
{data_context}{limits_context}
ПРАВИЛА ПОВЕДЕНИЯ:
1. Ты НИКОГДА не считаешь числа самостоятельно — всегда используй инструменты для расчётов
2. Отвечай только на финансовые вопросы. На другие темы — вежливо откажи
3. Если пользователь просит установить лимит и формулировка нечёткая — уточни через save_pending_confirmation
4. Всегда отвечай на русском языке
5. Используй эмодзи для наглядности: 💰 📊 ⚠️ ✅ 📁
6. Для установки лимита всегда уточняй: категорию, сумму и период (week/month/year)

ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
- load_transactions(period) — загрузить транзакции за период
- set_limit(category, amount, period) — установить лимит по категории
- check_limit_violations() — проверить нарушения лимитов
- get_spending_report(period) — получить отчёт за период
- list_limits() — показать все лимиты
- categorize_transaction(merchant) — определить категорию мерчанта
- find_cheaper(category) — найти дешевле в категории
- check_refund(merchant) — проверить возможность возврата
- save_pending_confirmation(action, params) — сохранить действие для подтверждения

Отвечай кратко и по делу. Если данных нет — честно скажи об этом."""
