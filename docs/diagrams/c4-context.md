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
    PriceAPI["💰 Price Comparison API\nopt-in\nПоиск альтернативных цен"]

    User -->|"файлы + сообщения"| TG
    TG -->|"webhook апдейты"| PFA
    PFA -->|"ответы + кнопки"| TG
    TG --> User
    PFA -->|"LLM inference"| Mistral
    PFA -->|"price lookup"| PriceAPI
```

## Границы системы

**Внутри PFA:**
- Telegram Bot сервер (aiogram)
- Agent Orchestrator (LangGraph)
- Все бизнес-компоненты (Categorizer, Limit Engine, Report Generator и др.)
- Local LLM Qwen3.5-9B (Ollama) — fallback при недоступности Mistral API
- Session Storage (JSON-файлы)
- Observability stack (Prometheus, Grafana)

**Вне PFA (внешние системы):**
- Telegram: только транспорт, PFA не хранит Telegram-данные
- Mistral API: основной LLM; при таймауте/ошибке → fallback на локальный Qwen3.5-9B
- Price API: опционально, с fallback на оффлайн-базу

**Вне scope PoC:**
- Банковские API в реальном времени
- Push-уведомления (планируется фаза 2)
- Мобильное приложение
