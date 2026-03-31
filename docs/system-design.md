# System Design — Personal Finance Assistant (PFA)

> AI-агент для анализа расходов через Telegram Bot
> Статус: PoC | Версия: 1.0

---

## 1. Ключевые архитектурные решения

| Решение | Выбор | Обоснование |
|---------|-------|-------------|
| **Канал доставки** | Telegram Bot (aiogram 3.x) | Zero-install, знакомый UX, поддержка файлов и inline-кнопок |
| **Оркестрация агента** | LangGraph (ReAct Tool Calling) | LLM сам выбирает инструменты; явный граф ограничивает max_steps и stop conditions |
| **LLM** | Mistral API (по умолчанию) → Qwen3.5-9B локально (fallback) | Mistral бесплатно для MVP — резерв при таймауте/ошибке API |
| **Категоризация** | Hybrid: keyword-rules → embedding-similarity → LLM fallback | Детерминированный путь для известных merchant'ов, LLM только для edge-case |
| **Хранение сессий** | JSON-файлы на диске (PoC) | Без внешних зависимостей; миграция на Redis/SQLite — фаза 2 |
| **Арифметика** | Детерминированный Python (pandas) | LLM никогда не считает числа — только генерирует текст |
| **Защита PII** | Маскирование до передачи в LLM; хэш Telegram ID (SHA-256+salt) | Privacy-by-design, ограничение поверхности атаки |
| **Инфраструктура** | Docker Compose (одна машина) | PoC-масштаб; production-путь — Kubernetes |

---

## 2. Модули и их роли

```
┌─────────────────────────────────────────────────────────────────┐
│  Telegram Bot Layer (aiogram 3.x)                               │
│  Роль: точка входа, роутинг сообщений, отправка ответов         │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│  Agent Orchestrator (LangGraph)                                 │
│  Роль: планирование шагов, вызов инструментов, управление       │
│        контекстом, retry/fallback                               │
└────┬──────────┬──────────┬──────────────┬───────────────────────┘
     │          │          │              │
┌────▼───┐ ┌───▼────┐ ┌───▼──────┐ ┌────▼────────────┐
│ File   │ │ Categ- │ │  Limit   │ │  Recommend-     │
│ Parser │ │ orizer │ │  Engine  │ │  ation Engine   │
│        │ │        │ │          │ │                 │
│pandas  │ │rules + │ │NL→struct │ │Refund + Price   │
│openpyxl│ │embed.  │ │pydantic  │ │Comparator tools │
└────┬───┘ └───┬────┘ └───┬──────┘ └────┬────────────┘
     │         │          │             │
┌────▼─────────▼──────────▼─────────────▼────────────────────────┐
│  Session Storage                                                │
│  Роль: состояние пользователя, транзакции, лимиты, история      │
│  JSON-файлы на диске; ключ — hashed(telegram_id)               │
└─────────────────────────────────────────────────────────────────┘
```

| Модуль | Технология | Роль |
|--------|-----------|------|
| **Telegram Bot** | aiogram 3.x | Приём/отправка сообщений и файлов, inline-кнопки |
| **File Parser** | pandas, openpyxl | Валидация и нормализация `.xlsx/.csv` |
| **Categorizer** | rules + sentence-transformers + LLM | Категоризация транзакций |
| **NL Limit Parser** | LLM (few-shot) + Pydantic validation | NL → `{category, amount, period}` |
| **Limit Engine** | Детерминированный Python | Сравнение трат с лимитами, выявление нарушений |
| **Price Comparator** | HTTP tool + offline DB | Поиск дешевле на рынке |
| **Refund Checker** | Rules engine | Проверка применимости политик возврата |
| **Report Generator** | Jinja2, markdown | Форматирование ответов, inline-кнопки |
| **Session Storage** | JSON + in-memory cache | Хранение состояния и истории |
| **Observability** | structlog + Prometheus + Grafana | Метрики, логи, алерты |
| **Guardrails** | Input sanitizer, prompt validator | Защита от инъекций, out-of-scope запросов |

---

## 3. Основной Workflow

```
[Пользователь] → отправляет сообщение или файл .xlsx/.csv
       ↓
[Bot] → передаёт в Orchestrator
       ↓
[Pre-flight Guard] → rate limit / file size / out-of-domain / PII masking
       ↓ (нарушение → немедленный отказ без LLM)
[Context Builder] → system prompt + tool definitions + агрегаты трат + история
       ↓
╔══════════════════════════════════════╗
║  ReAct Loop (LLM управляет потоком)  ║
║                                      ║
║  [LLM Node] → думает что сделать     ║
║       ↓                              ║
║  tool_call? → [Tool Node] → результат║
║       ↑___________________________|  ║
║                                      ║
║  финальный текст → выход из цикла    ║
╚══════════════════════════════════════╝
       ↓
[Response Builder] → markdown + inline-кнопки
       ↓
[Bot] → отправляет ответ
```

**Пример: «покажи перетраты на кофе»**
```
LLM: вызвать load_transactions(period="last_month")
  → ToolMessage: список транзакций
LLM: вызвать check_limits(category="Кофе")
  → ToolMessage: {spent: 2100, limit: 300, violation: true}
LLM: вызвать find_cheaper(category="Кофе")
  → ToolMessage: [{name: "Бренд Z", price: 290, savings_pct: 31}]
LLM: финальный текст "В марте на кофе потрачено 2100₽..."
```

---

## 4. State / Memory / Context

### Session State (per user)
```json
{
  "user_id_hash": "sha256(telegram_id + salt)",
  "transactions": [...],
  "limits": {"coffee": {"amount": 300, "period": "week"}},
  "last_file_ts": "ISO8601",
  "conversation_history": [...последние 10 сообщений...],
  "pending_confirmation": null
}
```

### Context Budget (LLM)
| Слот | Размер | Содержимое |
|------|--------|-----------|
| System prompt | ~500 токенов | Роль, правила, формат вывода |
| User data summary | ≤1500 токенов | Агрегаты трат (не сырые строки) |
| Conversation history | ≤1000 токенов | Последние 10 сообщений |
| Current task | ≤500 токенов | Запрос пользователя + параметры |
| **Итого** | **≤3500 токенов** | Остаток для ответа модели |

**Правила управления контекстом:**
- Сырые транзакции в LLM **не передаются** — только агрегаты (топ-5 категорий, суммы)
- История обрезается по скользящему окну (10 сообщений)
- PII маскируется перед включением в промпт: `"Starbucks Москва ул.Ленина 5"` → `"Starbucks [LOC]"`

### Memory Policy
- **Short-term**: conversation history в памяти процесса (сбрасывается при рестарте)
- **Long-term**: JSON-файл на диске; TTL файлов с транзакциями — 7 дней
- **No cross-user memory**: каждый пользователь изолирован по hashed ID

---

## 5. Retrieval-контур

PoC использует **lightweight retrieval** без полноценного vector store:

```
Транзакция: "STARBUCKS COFFEE #1234"
     ↓
1. Keyword match: "starbucks" → category="Кофе"  [детерминировано]
     ↓ нет
2. Embedding similarity (sentence-transformers/paraphrase-multilingual-MiniLM):
   embed("starbucks coffee") vs embed(known_categories)
   cosine ≥ 0.75 → category="Кофе"             [ML]
     ↓ нет
3. LLM call: "Какая категория у транзакции X?"
   [одиночный вызов, температура=0]              [LLM]
     ↓
Результат + confidence score → Categorizer output
```

**Индекс категорий**: ~50 категорий с текстовыми описаниями и примерами merchant'ов.
**Reranking**: не нужен на PoC-масштабе.
**Ограничения**: оффлайн-база цен — статичный JSON (~10K товаров, обновление вручную).

---

## 6. Tool / API интеграции

| Tool | Протокол | Timeout | Fallback |
|------|----------|---------|----------|
| **Telegram Bot API** | HTTPS webhook/polling | 60s (Telegram ограничение) | Long-polling при недоступности webhook |
| **Mistral API** (основной LLM) | HTTPS REST (OpenAI-compatible) | 30s | Qwen3.5-9B локально |
| **Local LLM** (Qwen3.5-9B, Ollama) | localhost REST | 15s | Детерминированный fallback + уведомление пользователю |
| **Price Comparison API** | HTTPS REST | 5s | Оффлайн JSON-база |

Все tool-вызовы — через изолированные async-функции с валидацией ответа (Pydantic).

---

## 7. Failure Modes, Fallback и Guardrails

### Failure Modes
| Сценарий | Вероятность | Обработка |
|----------|-------------|-----------|
| Mistral API таймаут / ошибка | Средняя | Fallback на локальный Qwen3.5-9B; прозрачно для пользователя |
| Локальный Qwen недоступен (если Mistral уже упал) | Низкая | Fallback на rule-based + уведомление пользователя |
| Некорректный формат файла | Высокая | Валидация в FileParser; понятное сообщение об ошибке |
| NL-парсинг с низкой уверенностью | Средняя | Запрос подтверждения через inline-кнопки |
| Price API недоступен | Средняя | Оффлайн-база с меткой «⚠️ Данные могут быть устаревшими» |
| Webhook Telegram недоступен | Низкая | Long-polling как fallback |
| OOM при большом файле | Низкая | Лимит 50 MB + streaming чтение |
| Out-of-domain запрос | Высокая | Guardrail на уровне orchestrator; отказ с редиректом |

### Guardrails
1. **Input sanitizer**: strip HTML/JS, проверка длины (≤4096 символов)
2. **Domain guard**: если запрос не про финансы → вежливый отказ без вызова LLM
3. **PII masker**: удаление email, телефонов, карточных номеров из данных перед LLM
4. **Output validator**: Pydantic-схемы для всех структурированных выходов LLM
5. **Confidence threshold**: NL-парсинг < 0.8 → clarification loop, не применяется автоматически
6. **Rate limiter**: не более 5 запросов в минуту с одного Telegram ID

---

## 8. Технические и операционные ограничения

| Параметр | Целевое значение | Обоснование |
|----------|-----------------|-------------|
| **p95 latency** (файл ≤5000 строк) | < 15 сек | CPU-обработка; локальная LLM |
| **p95 response time** (NL-запрос) | < 5 сек | UX-порог терпения |
| **TTFI** (Time-to-first-insight) | < 90 сек | Критерий успеха PoC |
| **Uptime** | ≥ 95% | PoC; не production SLA |
| **Max concurrent users** | 50 | Ограничение ресурсов сервера |
| **Max file size** | 50 MB | Telegram Bot API ограничение |
| **LLM context budget** | ≤ 3500 токенов | Оставить место для ответа модели |
| **LLM calls per request** | ≤ 3 | Контроль стоимости и latency |
| **Session storage TTL** | 7 дней | Баланс приватности и UX |
| **Memory (server)** | < 2 GB | Ограничение PoC-инфраструктуры |
| **LLM cost** | < $0.01 / запрос | Mistral medium: ~$0.005 при 3500 токенов |

---

## 9. Observability

| Что | Инструмент | Зачем |
|-----|-----------|-------|
| Структурированные логи | structlog + JSON | Дебаггинг, аудит |
| Метрики latency/errors | Prometheus + Grafana | SLO мониторинг |
| LLM call трейсинг | LangSmith / MLflow | Качество промптов, стоимость |
| Алерты | Grafana Alerting | p95 > 10s, error rate > 5% |
| Eval pipeline | pytest + golden set | Регрессионное тестирование качества |

---

## Диаграммы

- [C4 Context](diagrams/c4-context.md)
- [C4 Container](diagrams/c4-container.md)
- [C4 Component](diagrams/c4-component.md)
- [Workflow](diagrams/workflow.md)
- [Data Flow](diagrams/data-flow.md)

## Спецификации модулей

- [Retriever / Categorizer](specs/retriever.md)
- [Tools & APIs](specs/tools-apis.md)
- [Memory & Context](specs/memory-context.md)
- [Agent / Orchestrator](specs/agent-orchestrator.md)
- [Serving & Config](specs/serving-config.md)
- [Observability & Evals](specs/observability-evals.md)
