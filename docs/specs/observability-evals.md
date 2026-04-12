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

## Запуск Observability Stack

### Старт

```bash
docker-compose up -d
```

### Grafana

- URL: **http://localhost:3000**
- Логин: `admin` / пароль из `GRAFANA_ADMIN_PASSWORD` (по умолчанию `admin`)
- Datasource Prometheus уже настроен автоматически через provisioning

**Полезные запросы для Explore (или создания panels):**

```promql
# Сколько запросов в минуту
rate(pfa_requests_total[1m])

# p95 latency
histogram_quantile(0.95, sum(rate(pfa_request_duration_seconds_bucket[5m])) by (le))

# Error rate
sum(rate(pfa_errors_total[5m])) by (component)

# Сколько раз срабатывал fallback
rate(pfa_fallback_total[5m])

# Заблокировано guardrail'ом
rate(pfa_guardrail_blocked_total[5m]) by (reason)

# Категоризация по методу (rules/embedding/llm/fallback)
rate(pfa_categorization_total[5m]) by (method)
```

### Prometheus

Prometheus scrape'ит бота напрямую: `http://bot:9090/metrics`

Посмотреть метрики сырыми:

```bash
# Через docker exec
docker-compose exec bot curl -s http://localhost:9090/metrics

# Или напрямую если проброшен порт
curl http://localhost:9090/metrics
```

> По умолчанию порт 9090 бота не пробрасывается наружу (только внутри pfa_net). Если нужен доступ снаружи, добавь в docker-compose.yml:
> ```yaml
> bot:
>   ports:
>     - "9090:9090"
> ```

---

## LLM Трейсинг (Langfuse)

Langfuse — open-source альтернатива LangSmith. Может работать self-hosted (в том же docker-compose) или через облако [cloud.langfuse.com](https://cloud.langfuse.com).

Интеграция через `langfuse.callback.CallbackHandler` — добавляется как LangGraph callback, не меняет логику агента.

### Вариант 1: Self-hosted (рекомендуется)

Раскомментируй сервисы `langfuse` и `langfuse-db` в `docker-compose.yml`:

```bash
docker-compose up -d
```

Langfuse будет доступен на **http://localhost:3001**. При первом входе создай аккаунт, затем перейди в Settings → API Keys и скопируй ключи.

### Вариант 2: Cloud

Зарегистрируйся на [cloud.langfuse.com](https://cloud.langfuse.com) → Settings → API Keys.

### Включение в боте

Добавь в `.env`:

```env
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://langfuse:3000   # self-hosted
# LANGFUSE_HOST=https://cloud.langfuse.com  # cloud
```

Перезапусти бота — в логах появится `langfuse_tracing_enabled`.

### Что трейсится автоматически

- Каждый LLM-вызов: входной prompt (без PII), выходной текст, latency, токены
- Каждый tool call: название, аргументы, результат
- Весь ReAct-цикл как одна сессия (trace)

### Просмотр трейсов

**http://localhost:3001 → Traces**

Каждый запрос — дерево: `trace → llm_call → tool_call → llm_call → ...`

---

## Eval Pipeline

> ⚠️ **Не реализовано в PoC.** Директория `tests/evals/` и golden sets не созданы.

Eval pipeline (автоматические тесты категоризатора, NL-парсера, out-of-domain) запланирован как следующий шаг после базовой функциональности. На данный момент тестирование проводится вручную через Telegram-интерфейс.
