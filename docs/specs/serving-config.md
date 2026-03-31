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
  llm-runner:    # Ollama с Qwen2.5-7B
  prometheus:    # Метрики
  grafana:       # Дашборды
```

Volumes:
- `session_data:/data/sessions` — JSON-файлы сессий
- `llm_models:/root/.ollama` — скачанные веса LLM
- `prometheus_data:/prometheus`
- `grafana_data:/var/lib/grafana`

---

## Конфигурация (env-переменные)

### Обязательные

| Переменная | Описание | Пример |
|-----------|----------|--------|
| `TELEGRAM_BOT_TOKEN` | Токен от BotFather | `123456789:AAH...xyz` |

### Опциональные

| Переменная | Default | Описание |
|-----------|---------|----------|
| `LLM_PROVIDER` | `api` | `api` (Mistral, по умолчанию) или `local` (Qwen) |
| `LLM_API_BASE_URL` | `https://api.mistral.ai/v1` | URL OpenAI-совместимого API |
| `LLM_API_KEY` | — | API ключ Mistral (обязателен при `LLM_PROVIDER=api`) |
| `LLM_FALLBACK_PROVIDER` | `local` | Провайдер при ошибке основного; `local` или `none` |
| `LLM_MODEL` | `mistral-small-latest` | Имя модели (Mistral) или имя модели в Ollama |
| `LLM_FALLBACK_MODEL` | `qwen3.5:9b` | Модель для fallback (Ollama) |
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
- `LLM_API_KEY`
- `PRICE_API_KEY` (если есть)

Хранятся только в `.env` (добавлен в `.gitignore`).

В production: использовать Docker Secrets или переменные окружения CI/CD.

---

## Версии моделей

| Модель | Версия PoC | Параметры | RAM |
|--------|-----------|-----------|-----|
| Mistral API | mistral-small-latest | API (основной, по умолчанию) | — |
| Qwen3.5 | 9B-Instruct-Q4_K_M | 9B (квантизованная, fallback) | ~6 GB |
| sentence-transformers | paraphrase-multilingual-MiniLM-L12-v2 | 118M | ~450 MB |

Переключить на локальный режим: `LLM_PROVIDER=local` в `.env`, убедиться что `llm-runner` запущен.
Отключить fallback на локальную модель: `LLM_FALLBACK_PROVIDER=none` (в этом случае при ошибке API — rule-based ответ).

---

## Healthcheck

```bash
# Bot health
curl http://localhost:8080/health

# LLM runner
curl http://localhost:11434/api/tags

# Prometheus
curl http://localhost:9090/-/healthy
```

---

## Минимальные требования сервера

| Ресурс | Minimum (PoC) | Recommended |
|--------|--------------|-------------|
| CPU | 4 vCPU | 8 vCPU |
| RAM | 8 GB | 16 GB |
| Disk | 20 GB | 50 GB |
| GPU | Нет (CPU inference) | 8GB VRAM (значительно быстрее) |
