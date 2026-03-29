# Spec: Agent / Orchestrator

## Фреймворк

**LangGraph** — граф состояний с явными переходами и ReAct-циклом.

Выбор обоснован:
- LLM сам решает какие инструменты вызвать и в каком порядке (настоящий агент)
- Явный граф → контроль stop conditions и max_steps (vs бесконечный цикл)
- Встроенный ToolNode + human-in-the-loop (confirmation step)
- Легкая интеграция с LangSmith для трейсинга каждого шага

---

## Ключевая идея: LLM управляет потоком

LLM получает в system prompt:
1. Описание роли и правил
2. Агрегированные данные о тратах пользователя
3. Список доступных инструментов (`tool_definitions` в формате OpenAI function calling)
4. Историю диалога (последние 10 сообщений + результаты инструментов)

LLM отвечает одним из двух вариантов:
- `tool_call: {name: "check_limits", args: {period: "march"}}` → система исполняет, результат добавляется в историю, LLM вызывается снова
- финальный текст (без tool_call) → агент завершает работу

---

## AgentState

```python
class AgentState(TypedDict):
    messages: list[BaseMessage]   # HumanMessage, AIMessage, ToolMessage
    user_hash: str
    session: UserSession          # транзакции, лимиты из хранилища
    step_count: int               # счётчик для max_steps
    error_count: int              # счётчик ошибок LLM подряд
```

`messages` — единственный источник истины для LLM. Каждый tool call и его результат добавляется сюда как `ToolMessage`.

---

## Граф состояний

```
START
  │
  ▼
[pre_flight_guard]  ← детерминированный, без LLM
  ├── rate_limit превышен ──▶ END (429)
  ├── файл слишком большой ──▶ END (error message)
  ├── явно out-of-domain   ──▶ END (refusal)
  └── PII masking + OK     ──▶ [context_builder]
  │
  ▼
[context_builder]
  • загружает сессию из Storage
  • формирует system_prompt с tool_definitions
  • добавляет агрегаты трат (не сырые строки!)
  • контролирует token budget (≤3500 токенов)
  │
  ▼
╔══════════════════════╗
║  [llm_node]          ║◄──────────────────────────┐
║  • вызов LLM         ║                           │
║  • retry 3x backoff  ║                           │
╚══════════════════════╝                           │
  │                                                │
  ├── tool_call в ответе ──▶ [tool_node]           │
  │                            • исполнить tool    │
  │                            • добавить          │
  │                              ToolMessage       │
  │                            • step_count += 1   │
  │                                    │           │
  │                                    └───────────┘ (цикл)
  │
  └── финальный текст ──▶ [response_builder]
                              │
                              ▼
                         [state_manager]
                         • сохранить историю
                         • сохранить изменения сессии
                              │
                              ▼
                             END
```

---

## Инструменты (tool definitions)

```python
tools = [
    load_transactions,       # получить транзакции из сессии
    categorize_transaction,  # определить категорию merchant'а
    set_limit,               # установить лимит {category, amount, period}
    check_limits,            # проверить нарушения лимитов
    find_cheaper,            # найти альтернативу дешевле (Price API)
    check_refund,            # проверить возможность возврата
    get_report,              # агрегированный отчёт за период
    save_pending_confirmation # сохранить ожидающее подтверждение
]
```

Каждый инструмент — async Python-функция с типизированными аргументами (Pydantic).
LLM видит их через `bind_tools()` в LangChain.

**Пример вызова LLM:**

```
User: "покажи где я больше всего трачу на кофе"

→ LLM: tool_call load_transactions({period: "last_month"})
→ ToolMessage: [{date, amount, merchant, category}, ...]
→ LLM: tool_call check_limits({category: "Кофе"})
→ ToolMessage: {spent: 2100, limit: 300, violation: true}
→ LLM: финальный текст "В марте вы потратили на кофе 2100₽..."
```

---

## Pre-flight Guard (детерминированный, без LLM)

Выполняется **до** любого LLM-вызова:

1. **Rate limit**: ≤ 5 запросов/минуту на user_hash → 429
2. **File size**: > 50 MB → отказ с подсказкой
3. **Domain check**: явно не финансовая тема (regex: курс валют, погода, стихи...) → вежливый отказ без LLM
4. **PII masking**: email → `[EMAIL]`, телефон → `[PHONE]`, номер карты → `[CARD]`

Зачем без LLM: быстро (< 1ms), предсказуемо, не тратит токены.

---

## Confirmation Loop (human-in-the-loop)

Когда LLM вызывает `save_pending_confirmation` (низкая уверенность):

```
LLM: tool_call save_pending_confirmation({params, expires_in: 600})
  ↓
Bot отправляет: "Правильно ли я понял: лимит 300₽ на кофе в неделю?"
                [✅ Да] [❌ Нет]
  ↓
Пользователь нажимает кнопку → callback_query
  ↓
Новый вход в граф с intent=callback
  ├── confirmed → LLM получает: tool_call set_limit(pending_params) → обычный flow
  └── rejected  → LLM получает: "пользователь отверг, уточни параметры"
```

TTL pending: 10 минут. При истечении — тихая отмена.

---

## Stop Conditions

| Условие | Действие |
|---------|----------|
| LLM вернул финальный текст (нет tool_call) | Нормальное завершение |
| `step_count >= 10` | Принудительная остановка + финальный ответ с предупреждением |
| `error_count >= 3` (ошибки LLM подряд) | Fallback-ответ + логирование |
| Tool вернул `fatal=True` | Немедленная остановка с сообщением об ошибке |
| Rate limit превышен | 429 до входа в граф |
| Total timeout 30s | Прерывание + "⚠️ Запрос занял слишком много времени" |

---

## Retry и Fallback политика

| Компонент | Retry | Fallback |
|-----------|-------|----------|
| LLM node | 3× exponential backoff (1s, 2s, 4s) | Шаблонный ответ + "AI временно недоступен" |
| Tool: find_cheaper (Price API) | 1× immediate | Оффлайн-база с меткой "данные могут быть устаревшими" |
| Tool: categorize (LLM fallback) | — | Категория "Другое" + флаг для ручной разметки |
| Telegram send | 3× backoff | Log error, skip (сообщение потеряно) |
| Session Storage write | 3× | Log error, warn user "данные могут не сохраниться" |

---

## Ограничения

| Параметр | Значение |
|----------|----------|
| Max LLM calls per request | 10 (= max_steps) |
| Max tool calls per request | 10 (в рамках max_steps) |
| Max retry per LLM call | 3 |
| Token budget (input) | ≤ 3500 токенов |
| Max concurrent requests per user | 1 (остальные в очереди) |
| Total request timeout | 30s |
| Pending confirmation TTL | 10 минут |
