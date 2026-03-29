# Spec: Observability & Evals

## Метрики (Prometheus)

### Latency и Throughput

| Метрика | Тип | Labels | Описание |
|---------|-----|--------|----------|
| `pfa_request_duration_seconds` | Histogram | `intent, status` | Сквозная latency: от сообщения до ответа |
| `pfa_llm_call_duration_seconds` | Histogram | `model, call_type` | Время LLM-вызова |
| `pfa_tool_call_duration_seconds` | Histogram | `tool_name` | Время выполнения инструмента |
| `pfa_requests_total` | Counter | `intent, status` | Всего запросов |
| `pfa_active_requests` | Gauge | — | Запросы в обработке |

### Качество

| Метрика | Тип | Labels | Описание |
|---------|-----|--------|----------|
| `pfa_llm_confidence` | Histogram | `call_type` | Уверенность NL-парсинга |
| `pfa_fallback_total` | Counter | `reason` | Число активаций fallback |
| `pfa_retry_total` | Counter | `component` | Число retry по компонентам |
| `pfa_clarification_total` | Counter | — | Запросы подтверждения (confidence < 0.8) |

### Стоимость

| Метрика | Тип | Labels | Описание |
|---------|-----|--------|----------|
| `pfa_llm_tokens_total` | Counter | `model, type` | Токены (input / output) |
| `pfa_llm_cost_usd_total` | Counter | `model` | Накопленная стоимость (API mode) |

### Надёжность

| Метрика | Тип | Labels | Описание |
|---------|-----|--------|----------|
| `pfa_errors_total` | Counter | `component, error_type` | Ошибки по компонентам |
| `pfa_llm_timeout_total` | Counter | `model` | Таймауты LLM |
| `pfa_guardrail_blocked_total` | Counter | `reason` | Заблокированные запросы |

---

## Ключевые Prometheus запросы

```promql
# p95 latency по intent
histogram_quantile(0.95, sum(rate(pfa_request_duration_seconds_bucket[5m])) by (le, intent))

# Процент fallback от всех запросов
sum(rate(pfa_fallback_total[5m])) / sum(rate(pfa_requests_total[5m])) * 100

# Error rate
sum(rate(pfa_errors_total[5m])) by (component)

# Средняя уверенность NL-парсинга
histogram_quantile(0.50, sum(rate(pfa_llm_confidence_bucket[5m])) by (le))

# Стоимость LLM за час
sum(increase(pfa_llm_cost_usd_total[1h])) by (model)
```

---

## Grafana Дашборды

**Dashboard 1: Operations**
- Request rate и error rate
- p50/p95 latency по intent
- Active requests
- Fallback rate

**Dashboard 2: LLM Quality**
- Confidence distribution (гистограмма)
- Fallback trigger reasons
- Tokens per request
- Cost per hour

**Dashboard 3: User Activity**
- Requests by intent (pie chart)
- Files processed per hour
- Limits set vs analyzed

---

## Алерты

| Алерт | Условие | Severity | Действие |
|-------|---------|----------|----------|
| High Latency | p95 > 10s за 5 мин | Warning | Проверить LLM runner |
| LLM Timeout Rate | > 20% за 5 мин | Critical | Проверить LLM; уведомить |
| Error Rate | > 5% за 5 мин | Warning | Смотреть логи |
| Bot Unavailable | health check fail | Critical | Рестартовать сервис |
| High Fallback Rate | > 30% за 10 мин | Warning | Проверить LLM качество |

---

## Логирование (structlog)

Все логи в JSON формате:

```json
{
  "ts": "2026-03-28T10:15:00.123Z",
  "level": "info",
  "event": "request_complete",
  "user_hash": "a3f8b2...",
  "intent": "set_limit",
  "duration_ms": 2340,
  "llm_calls": 1,
  "tool_calls": 1,
  "confidence": 0.91,
  "fallback_used": false,
  "status": "success"
}
```

**Правила логирования:**
- Никогда не логировать: содержимое сообщений, суммы, merchant names, user data
- Всегда логировать: latency, intent, status, confidence, fallback_used
- Уровень ERROR: неожиданные исключения с stack trace
- Уровень WARNING: retry, fallback, low confidence

---

## LLM Трейсинг (LangSmith / MLflow)

Каждый LLM-вызов трейсится:
- Input prompt (без PII)
- Output
- Latency, tokens, cost
- Validation result
- Confidence score

Используется для:
- Анализа качества промптов
- Выявления регрессий при смене модели
- Оптимизации token budget

---

## Eval Pipeline

### Автоматические тесты

```bash
# Запуск всех eval тестов
pytest tests/evals/ -v

# Тест категоризатора (F1 ≥ 0.92)
pytest tests/evals/test_categorizer.py

# Тест NL-парсинга лимитов (accuracy ≥ 0.90)
pytest tests/evals/test_limit_parser.py

# End-to-end smoke тест
pytest tests/evals/test_e2e.py
```

### Golden Sets

| Набор | Размер | Метрика | Target |
|-------|--------|---------|--------|
| Categorizer | 200 транзакций | F1 | ≥ 0.92 |
| NL Limit Parser | 100 NL-фраз | Accuracy | ≥ 0.90 |
| Out-of-domain | 50 примеров | Recall | 100% (все должны быть заблокированы) |
| Refusal | 30 примеров инъекций | Recall | 100% |

### Регрессионный запуск

При каждом изменении промптов или смене модели:
1. Запустить `pytest tests/evals/`
2. Если F1 упал > 2pp → блокировать merge
3. Результаты логируются в MLflow для сравнения версий

### Human Eval (демо-сессии)

- CSAT опрос через inline-кнопки после каждого анализа: «Насколько полезен ответ? [1-5]»
- Целевой CSAT: ≥ 4.2 / 5.0
- Hallucination check: вручную для выборки 20 рекомендаций в неделю
