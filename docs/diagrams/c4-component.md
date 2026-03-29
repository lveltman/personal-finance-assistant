# C4 Component Diagram — Agent Orchestrator

> Уровень: внутреннее устройство Agent Orchestrator — ядра системы.

```mermaid
C4Component
    title C4 Component — Agent Orchestrator (LangGraph)

    Container_Ext(bot, "Telegram Bot Service")
    Container_Ext(local_llm, "Local LLM Runner")
    Container_Ext(session_store, "Session Storage")
    Container_Ext(observability, "Observability")

    Container_Boundary(orch, "Agent Orchestrator") {

        Component(intent_router, "Intent Router",
            "Python / keyword rules",
            "Определяет тип запроса: set_limit / analyze / report / help / out-of-domain")

        Component(domain_guard, "Domain Guard",
            "Python / rules",
            "Отклоняет запросы вне финансовой домены без вызова LLM")

        Component(pii_masker, "PII Masker",
            "Python / regex + spacy",
            "Маскирует email, телефоны, адреса, номера карт перед передачей в LLM")

        Component(context_builder, "Context Builder",
            "Python",
            "Собирает system prompt + агрегаты трат + last N сообщений; контролирует token budget")

        Component(llm_caller, "LLM Caller",
            "Python / httpx async",
            "Вызов локального LLM → fallback на API; retry (3x), timeout 15s")

        Component(output_validator, "Output Validator",
            "Pydantic",
            "Валидирует структурированные выходы LLM по схемам (LimitParams, CategoryLabel и др.)")

        Component(tool_dispatcher, "Tool Dispatcher",
            "LangGraph ToolNode",
            "Маршрутизирует tool-вызовы к нужному инструменту; обрабатывает ошибки инструментов")

        Component(state_manager, "State Manager",
            "Python",
            "Читает/пишет сессию пользователя; разрешает конфликты лимитов")

        Component(response_builder, "Response Builder",
            "Jinja2 + markdown",
            "Форматирует ответ для Telegram; генерирует inline-кнопки подтверждения")
    }

    Rel(bot, intent_router, "user_message + file")
    Rel(intent_router, domain_guard, "если не распознан тип")
    Rel(intent_router, pii_masker, "распознанный запрос")
    Rel(pii_masker, context_builder, "очищенный контекст")
    Rel(context_builder, llm_caller, "промпт в рамках бюджета")
    Rel(llm_caller, local_llm, "inference")
    Rel(llm_caller, output_validator, "raw LLM output")
    Rel(output_validator, tool_dispatcher, "validated tool calls")
    Rel(tool_dispatcher, state_manager, "read/write state")
    Rel(state_manager, session_store, "persist")
    Rel(tool_dispatcher, response_builder, "tool results")
    Rel(response_builder, bot, "formatted response")
    Rel(llm_caller, observability, "latency, tokens, cost")
```

## Граф состояний LangGraph

```
START
  ↓
[intent_router] ──→ out_of_domain ──→ [refusal] ──→ END
  ↓
[domain_guard] ──→ blocked ──→ [safety_response] ──→ END
  ↓
[pii_masker]
  ↓
[context_builder]
  ↓
[llm_caller] ──→ error (3 retries) ──→ [fallback_response] ──→ END
  ↓
[output_validator] ──→ invalid ──→ [llm_caller] (retry, max 2)
  ↓
[tool_dispatcher]
  ├── tool=categorize ──→ [Categorizer]
  ├── tool=set_limit  ──→ [LimitEngine] ──→ confidence<0.8 ──→ [clarify_loop]
  ├── tool=analyze    ──→ [LimitEngine + RecommendationEngine]
  ├── tool=compare    ──→ [PriceComparator]
  └── tool=report     ──→ [ReportGenerator]
  ↓
[state_manager]
  ↓
[response_builder]
  ↓
END
```
