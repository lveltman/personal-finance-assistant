# Data Flow Diagram — PFA

> Как данные проходят через систему, что хранится, что логируется.

## Основной поток данных

```mermaid
flowchart TD
    subgraph INPUT["Входные данные"]
        F[".xlsx / .csv файл"]
        M["NL сообщение пользователя"]
    end

    subgraph SANITIZE["Санитизация (Bot → Orchestrator)"]
        FS["File Validator\n• размер ≤50MB\n• формат xlsx/csv\n• кодировка UTF-8"]
        PI["PII Masker\n• email → [EMAIL]\n• телефон → [PHONE]\n• адрес → [LOC]\n• карта → [CARD]"]
    end

    subgraph PROCESS["Обработка (Tool Layer)"]
        FP["File Parser\n→ DataFrame[date, amount, merchant]"]
        CAT["Categorizer\n→ [(merchant, category, confidence)]"]
        NLP["NL Limit Parser (LLM)\n→ {category, amount, period}"]
        LE["Limit Engine\n→ {violations, overage_pct}"]
        REC["Recommendation Engine\n→ [actions: refund/compare]"]
        REP["Report Generator\n→ markdown text + buttons"]
    end

    subgraph STORAGE["Хранение"]
        SS[("Session Storage\nJSON files\nTTL: 7 дней")]
        LOG[("Logs\nstructlog JSON\nTTL: 30 дней")]
        MET[("Metrics\nPrometheus TSDB\nTTL: 15 дней")]
    end

    subgraph LLM_BOX["LLM (локальный / API)"]
        LLM["Qwen2.5-7B\nвход: ≤3500 токенов\nвыход: ≤500 токенов"]
    end

    F --> FS --> FP --> CAT
    M --> PI --> NLP
    NLP --> LLM
    CAT --> LLM
    LLM --> CAT
    CAT --> SS
    NLP --> LE
    LE --> SS
    SS --> LE
    LE --> REC
    REC --> REP
    REP --> OUTPUT["Ответ в Telegram"]

    FP --> LOG
    NLP --> LOG
    LLM --> LOG
    LLM --> MET
    LE --> MET
```

## Что хранится и где

| Данные | Хранилище | TTL | Формат | Чувствительность |
|--------|-----------|-----|--------|-----------------|
| Транзакции пользователя | JSON-файл на диске | 7 дней | `[{date, amount, merchant, category}]` | 🔴 Высокая |
| Лимиты пользователя | JSON-файл на диске | До удаления | `{category: {amount, period}}` | 🟡 Средняя |
| История диалога | In-memory + JSON | Текущая сессия (≤10 сообщений) | `[{role, content}]` | 🟡 Средняя |
| Telegram ID | Только хэш (SHA-256+salt) | TTL сессии | HEX string | — (не восстановим) |
| Логи запросов | JSON log files | 30 дней | structlog JSON | 🟡 Средняя (без PII) |
| LLM метрики | Prometheus | 15 дней | Time series | 🟢 Низкая |
| Оффлайн-база цен | Docker volume | Обновляется вручную | JSON (~10K записей) | 🟢 Низкая |

## Что НЕ хранится

- ❌ Telegram username, имя, фамилия
- ❌ Сырые NL-сообщения (только распознанные параметры)
- ❌ Исходные файлы после парсинга (удаляются немедленно)
- ❌ Полные промпты LLM (только метаданные в трейсах)
- ❌ PII в любом виде (email, телефоны, адреса)

## Что логируется

```json
{
  "ts": "2026-03-28T10:15:00Z",
  "level": "info",
  "event": "llm_call",
  "user_hash": "a3f...8b2",
  "intent": "set_limit",
  "model": "qwen2.5-7b",
  "input_tokens": 312,
  "output_tokens": 48,
  "latency_ms": 2340,
  "confidence": 0.91,
  "fallback_used": false
}
```

**Никогда не логируется:** содержимое сообщений пользователя, суммы транзакций, названия merchant'ов.
