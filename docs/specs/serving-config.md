# Spec: Serving & Config

## Запуск

```bash
# Копировать пример конфига
cp .env.example .env
# Отредактировать .env (минимум: TELEGRAM_BOT_TOKEN)

# Запуск через Docker Compose
docker compose up --build

# Локально (без Docker)
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python src/bot/main.py
```

---

## Docker Compose сервисы

```yaml
services:
  bot:           # Telegram Bot + Agent Orchestrator
  prometheus:    # Метрики (опционально)
  grafana:       # Дашборды (опционально)
```

Volumes:
- `./data/sessions:/app/data/sessions` — JSON-файлы сессий (bind mount)
- `prometheus_data:/prometheus`
- `grafana_data:/var/lib/grafana`

> **Примечание:** Локальный LLM (Ollama/Qwen) не используется. Fallback — OpenAI GPT-4o-mini через API.

---

## Конфигурация (env-переменные)

### Обязательные

| Переменная | Описание | Пример |
|-----------|----------|--------|
| `TELEGRAM_BOT_TOKEN` | Токен от BotFather | `123456789:AAH...xyz` |

### Опциональные

| Переменная | Default | Описание |
|-----------|---------|----------|
| `MISTRAL_API_KEY` | — | API ключ Mistral (основной LLM) |
| `OPENAI_API_KEY` | — | API ключ OpenAI — для fallback на GPT-4o-mini при недоступности Mistral |
| `LLM_MODEL` | `mistral-medium-latest` | Модель Mistral |
| `LLM_FALLBACK_MODEL` | `gpt-4o-mini` | Модель OpenAI для fallback |
| `LLM_TIMEOUT_S` | `15` | Таймаут LLM-запроса в секундах |
| `MAX_FILE_SIZE_MB` | `50` | Максимальный размер файла |
| `SESSION_TTL_DAYS` | `7` | TTL JSON-сессий |
| `RATE_LIMIT_RPM` | `5` | Запросов в минуту на пользователя |
| `CONFIDENCE_THRESHOLD` | `0.8` | Порог уверенности для NL-парсинга |
| `PRICE_API_URL` | — | URL внешнего price API |
| `PRICE_API_TIMEOUT_S` | `5` | Таймаут price API |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` |
| `METRICS_PORT` | `9090` | Порт Prometheus метрик |
| `PII_CHECK_ENABLED` | `true` | Включить PII-маскирование |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Пароль Grafana |

---

## Секреты

Никогда не коммитить в git:
- `TELEGRAM_BOT_TOKEN`
- `MISTRAL_API_KEY`
- `PRICE_API_KEY` (если есть)

Хранятся только в `.env` (добавлен в `.gitignore`).

В production: использовать Docker Secrets или переменные окружения CI/CD.

---

## Версии моделей

| Модель | Версия PoC | Параметры | RAM |
|--------|-----------|-----------|-----|
| Mistral API | mistral-medium-latest | API (основной) | — |
| OpenAI | gpt-4o-mini | API (fallback при недоступности Mistral) | — |

Отключить fallback: убрать `OPENAI_API_KEY` из `.env` — при ошибке Mistral вернётся rule-based ответ с предупреждением.

---

## Healthcheck

```bash
# Prometheus
curl http://localhost:9090/-/healthy
```

---

## Минимальные требования сервера

| Ресурс | Minimum (PoC) | Recommended |
|--------|--------------|-------------|
| CPU | 2 vCPU | 4 vCPU |
| RAM | 1 GB | 2 GB |
| Disk | 5 GB | 10 GB |
| GPU | Не требуется (все LLM — через API) | — |
