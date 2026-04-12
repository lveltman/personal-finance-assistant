# C4 Container Diagram — PFA

> Уровень: контейнеры внутри PFA — процессы, хранилища, их взаимодействие.

```mermaid
flowchart TB
    User(["👤 Пользователь"])
    TG["📱 Telegram API\n(внешний)"]
    Mistral["🤖 Mistral API\nосновной LLM\n(внешний)"]
    PriceAPI["💰 Price API\nopt-in\n(внешний)"]

    subgraph PFA["Personal Finance Assistant"]
        Bot["🤖 Telegram Bot Service\nPython / aiogram 3.x\n──────────────────\nТочка входа: приём апдейтов,\nроутинг, отправка ответов\n[Stateless]"]

        Orch["🧠 Agent Orchestrator\nPython / LangGraph\n──────────────────\nReAct-цикл: LLM выбирает\nинструменты, retry/fallback\n[Stateless]"]

        FallbackLLM["☁️ OpenAI GPT-4o-mini\n(внешний API)\n──────────────────\nFallback при недоступности\nMistral API\n[Stateless]"]

        Tools["🔧 Tool Layer\nPython async\n──────────────────\nFileParser, Categorizer,\nLimitEngine, PriceComparator,\nRefundChecker, ReportGenerator"]

        Storage[("🗄️ Session Storage\nJSON files on disk\n──────────────────\nТранзакции, лимиты, история\nКлюч: hashed(telegram_id)\n[Stateful]")]

        Obs["📊 Observability\nPrometheus + Grafana\n+ structlog\n──────────────────\nМетрики, логи, алерты\n[Stateful]"]
    end

    User -->|"сообщения / файлы"| TG
    TG -->|"Webhook / Long-polling"| Bot
    Bot -->|"parsed message + context"| Orch
    Orch -->|"LLM inference — основной"| Mistral
    Orch -->|"LLM inference — fallback"| FallbackLLM
    Orch -->|"tool calls"| Tools
    Tools -->|"Price lookup opt-in"| PriceAPI
    Tools -->|"Read / Write session"| Storage
    Orch -->|"Load / Save context"| Storage
    Bot -->|"ответы + inline buttons"| TG
    Bot -->|"logs + metrics"| Obs
    Orch -->|"logs + LLM traces"| Obs
```

## Ключевые свойства контейнеров

| Контейнер | Масштабирование | Состояние |
|-----------|----------------|-----------|
| Telegram Bot Service | Горизонтально (несколько инстансов) | Stateless |
| Agent Orchestrator | Горизонтально | Stateless (состояние в Session Storage) |
| OpenAI GPT-4o-mini (fallback) | Внешний API | Stateless |
| Tool Layer | Часть Orchestrator процесса | Stateless |
| Session Storage | Вертикально (PoC: JSON; prod: Redis/SQLite) | Stateful |
| Observability | Отдельный Docker Compose stack | Stateful |
