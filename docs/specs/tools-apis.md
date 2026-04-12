# Spec: Tools & APIs

## Список инструментов

### 1. FileParser

**Назначение:** Загрузка и валидация `.xlsx/.csv` из Telegram.

**Контракт:**
```python
async def parse_file(file_bytes: bytes, filename: str) -> ParseResult:
    ...

@dataclass
class ParseResult:
    transactions: list[Transaction]  # нормализованные транзакции
    errors: list[str]                # строки, которые пропущены
    row_count: int
```

**Валидация:**
- Обязательные колонки: `date` (или синоним), `amount` (или синоним), хотя бы одна из `merchant`/`description`/`name`
- Размер файла: ≤ 50 MB
- Кодировка CSV: UTF-8, UTF-8-BOM, Windows-1251 (autodetect)
- Диапазон дат: последние 2 года

**Ошибки:**
| Код | Сообщение | Действие |
|-----|-----------|----------|
| `UNSUPPORTED_FORMAT` | Файл не .xlsx/.csv | HTTP 400; сообщение пользователю |
| `MISSING_COLUMNS` | Нет колонок date/amount | HTTP 422; список найденных колонок |
| `TOO_LARGE` | > 50 MB | HTTP 413 |
| `PARTIAL_PARSE` | Часть строк не распознана | 200 + `errors` в ответе |

**Side effects:** Файл удаляется из памяти после парсинга.

---

### 2. LimitEngine

**Назначение:** Установка и проверка лимитов по категориям.

**Контракт:**
```python
def set_limit(user_hash: str, params: LimitParams) -> LimitSetResult
def check_limits(user_hash: str, transactions: list[Transaction]) -> list[Violation]

@dataclass
class LimitParams:
    category: str
    amount: float   # в рублях
    period: Literal["day", "week", "month"]
    confidence: float

@dataclass
class Violation:
    category: str
    limit: float
    spent: float
    overage_pct: float
    transactions: list[Transaction]  # виновные транзакции
```

**Правила приоритизации конфликтов:** конкретный лимит (категория="кофе") > общий (категория="еда").

**Timeout:** нет (детерминированный Python).

---

### 3. PriceComparator (Tool)

**Назначение:** Найти альтернативу дешевле для merchant/товара.

**Контракт:**
```python
async def find_cheaper(merchant: str, category: str, amount: float) -> list[Alternative]

@dataclass
class Alternative:
    name: str
    price: float
    savings_pct: float
    source: Literal["api", "offline_db"]
    freshness: str  # "live" | "cached_24h" | "offline"
```

**Timeout:** 5 секунд на внешний API.

**Fallback:** При таймауте или ошибке API → поиск в оффлайн-JSON-базе (`data/price_db.json`, ~10K записей). Ответ содержит метку `"freshness": "offline"`.

**Side effects:** результаты кэшируются в памяти на 1 час (LRU cache, max 1000 записей).

**Защита:** URL-параметры санитизируются; только GET-запросы; без авторизации (публичный API).

---

### 4. RefundChecker (Tool)

**Назначение:** Проверить применимость политики возврата для транзакции.

**Контракт:**
```python
def check_refund(transaction: Transaction) -> RefundResult

@dataclass
class RefundResult:
    eligible: bool
    reason: str
    deadline_days: Optional[int]  # сколько дней осталось
    policy_source: str
```

**Реализация:** Rule-based (статичный JSON с политиками по категориям). Нет внешних вызовов.

**Timeout:** нет (детерминированный Python).

---

### 5. TextTransactionParser (Tool: `parse_transactions_from_text`)

**Назначение:** Извлечь транзакции из свободного текста пользователя без файла.

**Контракт:**
```python
@tool
def parse_transactions_from_text(text: str) -> str:
    ...
```

**Поведение:**
- LLM с `with_structured_output(ExtractedTransactions)` извлекает: date, amount, merchant
- Даты: вычисляются относительно сегодня («вчера», «три дня назад», «2026 03 05»)
- После извлечения: dateparser нормализует дату, `batch_categorize` расставляет категории
- Транзакции **добавляются** к существующим в сессии (мерж, не замена)
- Возвращает список добавленных транзакций + сводку расходов за месяц

**Пример вызова:**
```
User: "вчера суши 1200₽ и цветы 600₽"
→ LLM: tool_call parse_transactions_from_text("вчера суши 1200₽ и цветы 600₽")
→ Result: "✅ Добавлено 2 транзакций: ...\n📊 Расходы за месяц: 1800₽"
```

---

### 6. RecategorizationTool (Tool: `recategorize_all_transactions`)

**Назначение:** Пересчитать категории для всех транзакций в сессии.

**Когда использовать:** Категории пустые, показывают "Прочее" или "nan" после загрузки файла.

**Поведение:** Пробегает все транзакции, применяет keyword-rules → LLM fallback, сохраняет результат обратно в сессию.

---

### 7. ReportGenerator (Tool)

**Назначение:** Форматирование итогового ответа для Telegram.

**Контракт:**
```python
def generate_report(context: ReportContext) -> TelegramResponse

@dataclass
class TelegramResponse:
    text: str            # Markdown, ≤ 4096 символов
    parse_mode: str      # "MarkdownV2"
    reply_markup: dict   # inline keyboard JSON
```

**Ограничения:**
- Если текст > 4096 символов → разбить на части или отправить файлом
- Inline кнопки: до 5 кнопок на сообщение (UX)

---

## Внешние API

### Telegram Bot API

| Параметр | Значение |
|----------|----------|
| Протокол | HTTPS |
| Аутентификация | Bot Token в URL |
| Webhook timeout | 60s |
| Rate limit | ~30 сообщений/сек на бота |
| File download | `getFile` → HTTPS URL → скачать bytes |
| Fallback | Long-polling если webhook недоступен |

### Mistral API (основной LLM)

| Параметр | Значение |
|----------|----------|
| URL | Хардкожен в `mistralai` SDK (указывать не нужно) |
| Auth | `MISTRAL_API_KEY` env (секрет) |
| Timeout | 30s |
| Retry | 2 раза с backoff 1s, 2s |
| Fallback при провале | OpenAI GPT-4o-mini (автоматически через `with_fallbacks`) |
| Max cost per request | ~$0.005 (3500 токенов mistral-medium) |

### OpenAI GPT-4o-mini (fallback LLM)

| Параметр | Значение |
|----------|----------|
| Auth | `OPENAI_API_KEY` env (опционально) |
| Timeout | 30s |
| Retry | 1 раз |
| Fallback при провале | Rule-based ответ + "⚠️ AI временно недоступен" |
| Когда используется | Mistral API недоступен / таймаут / HTTP 5xx |
| Механизм | LangChain `ChatMistralAI.with_fallbacks([ChatOpenAI])` |
