# C4 Component Diagram — Agent Orchestrator

> Уровень: внутреннее устройство Agent Orchestrator — ядра системы.

```mermaid
C4Component
    title C4 Component — Agent Orchestrator (LangGraph ReAct)

    Container_Ext(bot, "Telegram Bot Service")
    Container_Ext(local_llm, "Local LLM Runner")
    Container_Ext(session_store, "Session Storage")
    Container_Ext(observability, "Observability")

    Container_Boundary(orch, "Agent Orchestrator") {

        Component(pre_guard, "Pre-flight Guard",
            "Python / rules (без LLM)",
            "Rate limit, размер файла, domain check (явно не финансы → отказ), PII masking — всё до LLM")

        Component(context_builder, "Context Builder",
            "Python",
            "Собирает AgentState: system prompt с tool definitions + агрегаты трат + история; контролирует token budget")

        Component(llm_node, "LLM Node",
            "LangGraph / httpx async",
            "Отправляет весь AgentState в LLM. LLM отвечает: tool_call(name, args) или финальный текст. Mistral API → fallback Qwen3.5-9B. Retry 2x")

        Component(tool_node, "Tool Node",
            "LangGraph ToolNode",
            "Исполняет tool_call от LLM. Результат добавляется в AgentState как ToolMessage и управление возвращается LLM")

        Component(state_manager, "State Manager",
            "Python",
            "Читает/пишет сессию; разрешает конфликты лимитов; управляет pending confirmations")

        Component(response_builder, "Response Builder",
            "Jinja2 + markdown",
            "Форматирует финальный текст LLM для Telegram; добавляет inline-кнопки если нужно")
    }

    Rel(bot, pre_guard, "user_message + file")
    Rel(pre_guard, context_builder, "очищенное сообщение")
    Rel(context_builder, llm_node, "AgentState (messages[])")
    Rel(llm_node, local_llm, "fallback inference (если Mistral недоступен)")
    Rel(llm_node, tool_node, "tool_call: name + args")
    Rel(tool_node, state_manager, "read/write session")
    Rel(state_manager, session_store, "persist JSON")
    Rel(tool_node, llm_node, "ToolMessage с результатом (цикл)")
    Rel(llm_node, response_builder, "финальный текст (нет tool_call)")
    Rel(response_builder, bot, "formatted response")
    Rel(llm_node, observability, "latency, tokens, tool_calls")
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
║     ├── tool_call? ──→ [tool_node] ──→ добавить ToolMessage
║     │                    │                      │
║     │        ошибка инструмента?                │
║     │          ↓ да                             │
║     │      добавить error ToolMessage           │
║     │                                           │
║     └──────────────────────────────────────────┘
║     │                        ↑ цикл
║     └── финальный текст? ──→ выход из цикла
║                              ║
║  Stop conditions:            ║
║  • нет tool_call в ответе    ║
║  • достигнут max_steps (10)  ║
║  • Mistral + Qwen оба упали  ║
╚══════════════════════════════╝
  ↓
[response_builder]
  ↓
[state_manager] → сохранить историю в Session Storage
  ↓
END
```

## Инструменты, доступные LLM

LLM получает эти tool definitions в system prompt и сам решает что и когда вызвать:

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
