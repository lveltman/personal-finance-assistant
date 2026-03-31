# C4 Component Diagram — Agent Orchestrator

> Уровень: внутреннее устройство Agent Orchestrator — ядра системы.

```mermaid
flowchart TB
    Bot["📱 Telegram Bot Service\n(внешний контейнер)"]
    LocalLLM["💻 Local LLM Runner\nQwen3.5-9B\n(внешний контейнер)"]
    MistralAPI["🤖 Mistral API\n(внешний)"]
    Storage[("🗄️ Session Storage\n(внешний контейнер)")]
    Obs["📊 Observability\n(внешний контейнер)"]

    subgraph Orch["Agent Orchestrator"]
        Guard["🛡️ Pre-flight Guard\nPython / rules — без LLM\n──────────────────────\nRate limit, размер файла,\ndomain check, PII masking"]

        CtxBuilder["📋 Context Builder\nPython\n──────────────────────\nSystem prompt + tool definitions\n+ агрегаты трат + история\nКонтроль token budget ≤3500"]

        LLMNode["🧠 LLM Node\nLangGraph\n──────────────────────\nОтправляет AgentState в LLM\nПолучает: tool_call или текст\nMistral → fallback Qwen. Retry 2x"]

        ToolNode["🔧 Tool Node\nLangGraph ToolNode\n──────────────────────\nИсполняет tool_call от LLM\nДобавляет ToolMessage в стейт\nВозвращает управление LLM"]

        StateMgr["💾 State Manager\nPython\n──────────────────────\nЧитает/пишет сессию\nРазрешает конфликты лимитов\nPending confirmations"]

        RespBuilder["✉️ Response Builder\nJinja2 + markdown\n──────────────────────\nФорматирует текст для Telegram\nДобавляет inline-кнопки"]
    end

    Bot -->|"user_message + file"| Guard
    Guard -->|"очищенное сообщение"| CtxBuilder
    CtxBuilder -->|"AgentState messages"| LLMNode
    LLMNode -->|"основной inference"| MistralAPI
    LLMNode -->|"fallback inference"| LocalLLM
    LLMNode -->|"tool_call"| ToolNode
    ToolNode -->|"read/write"| StateMgr
    StateMgr -->|"persist"| Storage
    ToolNode -->|"ToolMessage цикл"| LLMNode
    LLMNode -->|"финальный текст"| RespBuilder
    RespBuilder -->|"formatted response"| Bot
    LLMNode -->|"latency, tokens, tool_calls"| Obs
```

## Граф состояний LangGraph (ReAct)

```
START
  ↓
[pre_flight_guard] ──→ rate_limit / out_of_domain / file_too_large
  │                         ↓
  │                    [refusal_node] ──→ END
  ↓
[context_builder]   ← загружает AgentState из Session Storage
  ↓
╔══════════════════════════════╗
║   ReAct Loop                 ║
║                              ║
║  [llm_node]                  ║
║     │                        ║
║     ├── tool_call → [tool_node] → добавить ToolMessage
║     │                               │
║     │        ошибка инструмента?    │
║     │          ↓ да                 │
║     │      добавить error msg       │
║     │                               │
║     └───────────────────────────────┘ цикл
║     │
║     └── финальный текст → выход
║
║  Stop conditions:
║  • нет tool_call в ответе
║  • достигнут max_steps (10)
║  • Mistral + Qwen оба упали
╚══════════════════════════════╝
  ↓
[response_builder]
  ↓
[state_manager] → сохранить историю в Session Storage
  ↓
END
```

## Инструменты, доступные LLM

LLM получает tool definitions в system prompt и сам решает что и когда вызвать:

| Tool | Описание | Когда LLM вызывает |
|------|----------|-------------------|
| `load_transactions` | Получить транзакции пользователя из сессии | Когда нужны данные о тратах |
| `categorize_transaction` | Определить категорию по merchant | При нечёткой категоризации |
| `set_limit` | Установить лимит по категории и периоду | При явном запросе лимита |
| `check_limits` | Проверить нарушения лимитов | При анализе трат |
| `find_cheaper` | Найти альтернативу дешевле | При рекомендациях экономии |
| `check_refund` | Проверить возможность возврата | При рекомендации возврата |
| `get_report` | Получить агрегированный отчёт за период | При запросе отчёта |
| `save_pending_confirmation` | Сохранить ожидающее подтверждение | При уверенности < 0.8 |
