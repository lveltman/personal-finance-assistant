# Personal Finance Assistant (PoC)

> AI-агент для анализа личных расходов через Telegram Bot
> LangGraph ReAct · Mistral API → OpenAI API (Ollama - Qwen3.5-9B) fallback · aiogram 3.x · Docker Compose

---

## Что делает PoC

- 📁 Загружает `.xlsx`/`.csv` с транзакциями (новые файлы **дополняют** базу, дубликаты пропускаются)
- 💬 Принимает транзакции текстом: «вчера суши 1200₽ и кофе 600₽» — LLM извлекает дату, сумму, мерчант
- 🏷️ Категоризирует расходы (keyword rules → LLM fallback)
- ⚙️ Принимает лимиты на естественном языке: «500₽ в неделю на кофе» или «общие траты 10000₽ в месяц»
- 📊 Показывает отчёты, топ-траты, нарушения лимитов
- 💡 Ищет дешевле, проверяет возможность возврата, составляет заявление на возврат
- 🛡️ Маскирует PII до передачи в LLM

---

## Быстрый запуск

### Шаг 1 — Предварительные требования

- Docker + Docker Compose
- Telegram Bot Token — получить через [@BotFather](https://t.me/BotFather)
- Mistral API Key — зарегистрироваться на [console.mistral.ai](https://console.mistral.ai) (есть бесплатный тариф)
- OpenAI API Key — для fallback на GPT-4o-mini при недоступности Mistral

### Шаг 2 — Настроить `.env`

```bash
cp .env.example .env
```

Открыть `.env` и заполнить:

```
TELEGRAM_BOT_TOKEN=123456789:AAH...xyz
MISTRAL_API_KEY=your_mistral_key
SESSION_SALT=any-random-secret-string
```

### Шаг 3 — Запустить

```bash
docker compose up --build -d
```

Бот запустится. Можно писать ему в Telegram.

### Шаг 4 — Fallback на GPT-4o-mini

При таймауте или ошибке Mistral бот автоматически переключается на OpenAI GPT-4o-mini (если `OPENAI_API_KEY` задан в `.env`).

### Просмотр логов

```bash
docker compose logs -f bot
```

### Остановить

```bash
docker compose down
```

---

## Для проверяющего

### Запуск

```bash
cp .env.example .env
# Заполнить TELEGRAM_BOT_TOKEN, MISTRAL_API_KEY, OPENAI_API_KEY, SESSION_SALT

docker compose up --build -d
```

### Что проверить и где

| Что | URL / команда | Ожидаемый результат |
|-----|--------------|---------------------|
| **Бот работает** | Написать в Telegram | Ответ агента |
| **Метрики (сырые)** | http://localhost:9091/metrics | Список `pfa_*` метрик |
| **Grafana дашборд** | http://localhost:3000 → логин `admin`/`admin` → dashboard **PFA Operations** | Графики request rate, latency, errors, categorization |
| **Prometheus** | http://localhost:9090/targets | Цель `bot:9090` со статусом `UP` |
| **LLM трейсы (Langfuse)** | https://cloud.langfuse.com → Traces | Дерево каждого запроса: LLM-вызовы + tool calls |
| **Логи бота** | `docker compose logs -f bot` | JSON-логи (structlog) |

### Сценарии для проверки функциональности

1. **Загрузка файла** — отправить боту `test/fixtures/sample_transactions.xlsx` (или любой `.xlsx` с колонками date/amount/merchant)
2. **Ввод текстом** — написать «вчера кофе 350₽ и обед в Теремке 480₽»
3. **Лимит** — «установи лимит 3000₽ в месяц на рестораны»
4. **Общий лимит** — «хочу тратить не больше 20000₽ в месяц»
5. **Отчёт** — «покажи где я больше всего трачу»
6. **Нарушения** — «где я превышаю лимиты?»
7. **Out-of-domain** — «расскажи про погоду» → бот вежливо отказывает без LLM-вызова

### Проверка метрик после нескольких запросов

```bash
# Счётчик запросов
curl -s http://localhost:9091/metrics | grep pfa_requests_total

# Категоризация по методу (rules / embedding / llm / fallback)
curl -s http://localhost:9091/metrics | grep pfa_categorization_total

# Guardrail срабатывания
curl -s http://localhost:9091/metrics | grep pfa_guardrail_blocked_total
```

---

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и инструкция |
| `/help` | Список возможностей |
| `/reset` | Удалить все данные сессии |

**Примеры запросов:**
- «Покажи расходы за месяц»
- «Установи лимит 1000₽ в месяц на рестораны»
- «Где я превышаю лимиты?»
- «Найди дешевле в категории кофе»
- «Можно вернуть покупку в Ozon?»

---

## Формат файла с транзакциями

Файл `.xlsx` или `.csv` с колонками (названия колонок гибкие):

| date / дата | amount / сумма | merchant / описание | category (опц.) |
|---|---|---|---|
| 2026-03-01 | 450 | Starbucks | |
| 2026-03-02 | 1200 | Лента | |

---

## Локальная разработка (без Docker)

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Создать .env с токенами
cp .env.example .env

# Поправить SESSION_DIR и DATA_DIR для локального пути
export SESSION_DIR=./data/sessions
export DATA_DIR=./data

python -m src.bot.main
```

---

## Структура проекта

```
src/
├── config.py               # Конфигурация из env
├── core/
│   ├── session.py          # Хранение сессий (JSON)
│   ├── file_parser.py      # Парсинг xlsx/csv
│   ├── categorizer.py      # Категоризация транзакций
│   └── limit_engine.py     # Проверка лимитов
├── agent/
│   ├── guard.py            # Pre-flight guard (rate limit, PII)
│   ├── prompts.py          # Системный промпт
│   ├── tools.py            # LangGraph @tool definitions
│   └── orchestrator.py     # ReAct агент (Mistral → GPT-4o-mini fallback)
└── bot/
    ├── handlers.py         # aiogram handlers
    └── main.py             # Точка входа
data/
├── merchant_rules.json     # Keyword rules для категоризации
└── prices.json             # Офлайн-база цен
docs/                       # Системный дизайн и диаграммы
```

---

## Документация

- [System Design](docs/system-design.md)
- [C4 Context](docs/diagrams/c4-context.md)
- [C4 Container](docs/diagrams/c4-container.md)
- [C4 Component](docs/diagrams/c4-component.md)
- [Data Flow](docs/diagrams/data-flow.md)
- [Agent / Orchestrator spec](docs/specs/agent-orchestrator.md)
