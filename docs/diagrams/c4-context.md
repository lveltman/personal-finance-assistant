# C4 Context Diagram — PFA

> Уровень: система целиком, пользователи, внешние сервисы и границы.

```mermaid
C4Context
    title C4 Context — Personal Finance Assistant

    Person(user, "Пользователь", "Физическое лицо, ведущее учёт расходов через Telegram")

    System(pfa, "Personal Finance Assistant", "Telegram-бот для анализа расходов, управления лимитами и получения рекомендаций")

    System_Ext(telegram, "Telegram", "Мессенджер; транспортный слой для сообщений, файлов и inline-кнопок")
    System_Ext(llm_api, "Mistral API", "Основной LLM-провайдер; OpenAI-compatible REST API")
    System_Ext(price_api, "Price Comparison API (opt-in)", "Внешний API для поиска альтернативных цен; опциональная интеграция")

    Rel(user, telegram, "Отправляет сообщения, файлы .xlsx/.csv, команды")
    Rel(telegram, pfa, "Webhook / Long-polling: передаёт апдейты")
    Rel(pfa, telegram, "Отправляет ответы, отчёты, inline-кнопки")
    Rel(pfa, llm_api, "HTTPS REST: основные LLM-запросы (по умолчанию)")
    Rel(pfa, price_api, "HTTPS REST: запрос альтернативных цен (opt-in)")
```

## Границы системы

**Внутри PFA:**
- Telegram Bot сервер (aiogram)
- Agent Orchestrator (LangGraph)
- Все бизнес-компоненты (Categorizer, Limit Engine, Report Generator и др.)
- Локальная LLM (Qwen3.5-9B, Ollama) — fallback при недоступности Mistral API
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
