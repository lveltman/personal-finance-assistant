"""Deterministic limit checking — no LLM involved."""
from collections import defaultdict
from datetime import date, datetime, timedelta

from src.core.models import Transaction


def _parse_date(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def _period_start(period: str) -> date:
    today = date.today()
    period = period.lower().strip()
    if period in ("week", "неделя", "неделю"):
        return today - timedelta(days=today.weekday())
    if period in ("month", "месяц", "месяца"):
        return today.replace(day=1)
    if period in ("year", "год", "года"):
        return today.replace(month=1, day=1)
    # Default: current month
    return today.replace(day=1)


def _aggregate_by_category(transactions: list[dict | Transaction], since: date) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for raw in transactions:
        tx = Transaction.model_validate(raw) if isinstance(raw, dict) else raw
        try:
            tx_date = _parse_date(tx.date)
        except ValueError:
            continue
        if tx_date >= since:
            totals[tx.category or "Прочее"] += tx.amount
    return dict(totals)


def check_violations(transactions: list[dict], limits: dict) -> list[dict]:
    """
    Returns list of violations: {category, limit, spent, period, overage, overage_pct}.
    """
    violations = []
    for category, limit_info in limits.items():
        amount_limit = float(limit_info.get("amount", 0))
        period = limit_info.get("period", "month")
        since = _period_start(period)
        totals = _aggregate_by_category(transactions, since)
        spent = totals.get(category, 0.0)
        if spent > amount_limit:
            overage = spent - amount_limit
            overage_pct = round((overage / amount_limit) * 100, 1) if amount_limit else 0
            violations.append({
                "category": category,
                "limit": amount_limit,
                "spent": round(spent, 2),
                "period": period,
                "overage": round(overage, 2),
                "overage_pct": overage_pct,
            })
    return violations


def get_spending_summary(transactions: list[dict], period: str = "month") -> dict:
    """Returns {total, by_category, period, tx_count}."""
    since = _period_start(period)
    totals = _aggregate_by_category(transactions, since)
    total = sum(totals.values())
    # Top 5 categories by spend
    top_categories = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:5]
    tx_in_period = [
        tx for tx in transactions
        if _parse_date((tx if isinstance(tx, Transaction) else Transaction.model_validate(tx)).date) >= since
    ]
    return {
        "total": round(total, 2),
        "by_category": {k: round(v, 2) for k, v in totals.items()},
        "top_categories": [(k, round(v, 2)) for k, v in top_categories],
        "period": period,
        "tx_count": len(tx_in_period),
        "since": since.isoformat(),
    }
