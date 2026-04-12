# C4 Context Diagram — PFA

> Уровень: система целиком, пользователи, внешние сервисы и границы.

```mermaid
flowchart LR
    User(["👤 Пользователь\nФизическое лицо,\nведущее учёт расходов"])

    subgraph PFA["🏦 Personal Finance Assistant"]
        Core["Telegram Bot + Agent Orchestrator\n+ Tool Layer + Storage + Observability"]
    end

    TG["📱 Telegram\nМессенджер — транспортный слой\nдля сообщений, файлов, кнопок"]
    Mistral["🤖 Mistral API\nОсновной LLM-провайдер\nOpenAI-compatible REST"]
    OpenAI["☁️ OpenAI API\nFallback LLM (GPT-4o-mini)\nOpenAI-compatible REST"]
    PriceAPI["💰 Price Comparison API\nopt-in\nПоиск альтернативных цен"]
    Langfuse["🔍 Langfuse\nLLM трейсинг\n(опционально, self-hosted)"]

    User -->|"файлы + сообщения"| TG
    TG -->|"webhook апдейты"| PFA
    PFA -->|"ответы + кнопки"| TG
    TG --> User
    PFA -->|"LLM inference (основной)"| Mistral
    PFA -->|"LLM inference (fallback)"| OpenAI
    PFA -->|"price lookup"| PriceAPI
    PFA -->|"traces (если включено)"| Langfuse
```

## Границы системы

**Внутри PFA:**
- Telegram Bot сервер (aiogram)
- Agent Orchestrator (LangGraph)
- Все бизнес-компоненты (Categorizer, Limit Engine, Report Generator и др.)
- OpenAI GPT-4o-mini — fallback при недоступности Mistral API (внешний API)
- Session Storage (JSON-файлы)
- Observability stack (Prometheus, Grafana)

**Вне PFA (внешние системы):**
- Telegram: только транспорт, PFA не хранит Telegram-данные
- Mistral API: основной LLM; при таймауте/ошибке → fallback на OpenAI GPT-4o-mini
- Price API: опционально, с fallback на оффлайн-базу

**Вне scope PoC:**
- Банковские API в реальном времени
- Push-уведомления (планируется фаза 2)
- Мобильное приложение
