# Spec: Agent / Orchestrator

## Фреймворк

**LangGraph** — граф состояний с явными переходами.

Выбор обоснован:
- Явный контроль потока (vs черный ящик LangChain AgentExecutor)
- Встроенный retry и breakpoints для дебаггинга
- Поддержка human-in-the-loop (confirmation step)
- Легкая интеграция с LangSmith для трейсинга

---

## Граф состояний

```
START
  │
  ▼
[rate_limit_check] ── превышен ──▶ END (429)
  │
  ▼
[intent_router]
  ├── out_of_domain ──▶ [refusal_node] ──▶ END
  ├── file_upload   ──▶ [file_processing_subgraph]
  ├── set_limit     ──▶ [limit_subgraph]
  ├── analyze       ──▶ [analysis_subgraph]
  ├── report        ──▶ [report_node] ──▶ END
  ├── help          ──▶ [help_node] ──▶ END
  └── callback      ──▶ [confirmation_handler]

[file_processing_subgraph]:
  parse_file → categorize_all → save_transactions → notify_user → END

[limit_subgraph]:
  pii_mask → build_context → llm_call → validate_output
    ├── confidence ≥ 0.8 ──▶ apply_limit → check_violations → respond → END
    └── confidence < 0.8 ──▶ save_pending → ask_clarify → END
                                                 ▲
  [confirmation_handler]: ──────────────────────┘
    confirmed  ──▶ apply_limit → respond → END
    rejected   ──▶ cancel_pending → notify → END
    expired    ──▶ cancel_pending → END (тихо)

[analysis_subgraph]:
  build_context → llm_call → validate → call_tools
    ├── PriceComparator (async, timeout 5s)
    ├── RefundChecker (sync)
    └── LimitEngine.check_limits()
  → aggregate_results → ReportGenerator → END
```

---

## Шаги (детально)

### intent_router
- **Метод:** keyword matching (детерминированный, без LLM)
- **Правила:**
  - Файл в апдейте → `file_upload`
  - Текст содержит `/` → command handler
  - Слова `лимит/limit/не хочу тратить/не более` → `set_limit`
  - Слова `анализ/расходы/покажи/сколько/трачу` → `analyze`
  - Слова `отчёт/report/итого` → `report`
  - Callback query → `callback`
  - Иначе → `analyze` (наиболее общий intent)
- **Fallback:** если запрос явно не про финансы → `out_of_domain`

### llm_call
- **Retry:** 3 попытки, exponential backoff (1s, 2s, 4s)
- **Timeout:** 15s per attempt
- **Fallback при полном провале:**
  - Категоризация → rule-based Level 1
  - NL-парсинг → попросить ввести параметры формой (`/setlimit 300 кофе неделя`)
  - Генерация текста → шаблонный ответ

### validate_output
- Pydantic-схема для каждого типа вывода
- При `ValidationError`: retry llm_call (max 2 раза) с инструкцией «Ответь строго в формате JSON»
- После 2 неудачных retry → fallback

---

## Stop Conditions

| Условие | Действие |
|---------|----------|
| Ответ отправлен пользователю | `END` |
| 3 ошибки LLM подряд | `END` с fallback-ответом |
| Tool вернул критическую ошибку | `END` с сообщением об ошибке |
| Rate limit превышен | `END` с 429 |
| Pending confirmation истёк | Тихий `END` без уведомления |

---

## Retry и Fallback политика

| Компонент | Retry | Fallback |
|-----------|-------|----------|
| LLM call | 3× backoff | Rule-based / шаблон |
| Price API | 1× immediate | Оффлайн база |
| Telegram send | 3× backoff | Log error, skip |
| File parse | 0 (fast fail) | Сообщение об ошибке |
| Session Storage write | 3× | Log error, continue (потеря данных с предупреждением) |

---

## Ограничения

| Параметр | Значение |
|----------|----------|
| Max LLM calls per request | 3 |
| Max tool calls per request | 5 |
| Max graph steps | 15 |
| Max retry loops | 3 per node |
| Max concurrent requests per user | 1 (queue остальные) |
| Request timeout (total) | 30s |
