# C4 Container Diagram — PFA

> Уровень: контейнеры внутри PFA — процессы, хранилища, их взаимодействие.

```mermaid
C4Container
    title C4 Container — Personal Finance Assistant

    Person(user, "Пользователь")
    System_Ext(telegram, "Telegram API")
    System_Ext(llm_api, "Mistral API (основной LLM)")
    System_Ext(price_api, "Price API (opt-in)")

    Container_Boundary(pfa, "Personal Finance Assistant") {

        Container(bot, "Telegram Bot Service", "Python / aiogram 3.x",
            "Точка входа: приём апдейтов от Telegram, роутинг на оркестратор, отправка ответов")

        Container(orchestrator, "Agent Orchestrator", "Python / LangGraph",
            "ReAct-цикл: планирование шагов, вызов инструментов, управление контекстом, retry/fallback")

        Container(local_llm, "Local LLM Runner", "Ollama",
            "Запуск Qwen3.5-9B локально; REST API на localhost; используется как fallback при недоступности Mistral API")

        Container(tool_layer, "Tool Layer", "Python async",
            "Изолированные инструменты: FileParser, Categorizer, LimitEngine, PriceComparator, RefundChecker, ReportGenerator")

        Container(session_store, "Session Storage", "JSON files on disk",
            "Состояние пользователя: транзакции, лимиты, история. Ключ — hashed(telegram_id)")

        Container(observability, "Observability", "Prometheus + Grafana + structlog",
            "Метрики latency/errors, структурированные логи, дашборды и алерты")
    }

    Rel(user, telegram, "Telegram messages / files")
    Rel(telegram, bot, "Webhook POST / Long-polling")
    Rel(bot, orchestrator, "Parsed message + user context")
    Rel(orchestrator, tool_layer, "Tool calls")
    Rel(orchestrator, llm_api, "LLM inference (основной)", "HTTPS")
    Rel(orchestrator, local_llm, "LLM inference (fallback при ошибке Mistral)")
    Rel(tool_layer, price_api, "Price lookup (opt-in)", "HTTPS")
    Rel(tool_layer, session_store, "Read / Write session")
    Rel(orchestrator, session_store, "Load / Save context")
    Rel(bot, telegram, "Send responses / inline buttons")
    Rel(bot, observability, "Logs + metrics")
    Rel(orchestrator, observability, "Logs + LLM traces")
```

## Ключевые свойства контейнеров

| Контейнер | Масштабирование | Состояние |
|-----------|----------------|-----------|
| Telegram Bot Service | Горизонтально (несколько инстансов) | Stateless |
| Agent Orchestrator | Горизонтально | Stateless (состояние в Session Storage) |
| Local LLM Runner | Вертикально (GPU/CPU) | Stateless |
| Tool Layer | Часть Orchestrator процесса | Stateless |
| Session Storage | Вертикально (PoC: JSON; prod: Redis/SQLite) | Stateful |
| Observability | Отдельный Docker Compose stack | Stateful |
