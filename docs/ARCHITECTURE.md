# ARCHITECTURE

Обновляется по мере роста системы. Текущее состояние — после **Блока A
(надёжность продакшена)** дорожной карты «прототип → продукт».

## Компоненты

```
                         ┌──────────────────────────────────────────────┐
 HTTP (frontend / API) ──► main.py: request-id middleware, latency-метрики │
                         └──────┬───────────────────────────────────────┘
                                ▼
                     routers/{analysis,batch,data,system}.py   (/api/v1)
                                │
        ┌───────────────────────┼──────────────────────────────┐
        ▼                       ▼                              ▼
core/llm_gateway.py     services/batch_service.py       routers/system.py
 (A.1/A.3/A.4/A.6)       + batch_processor.py            /health /metrics /queue
  │ token bucket          (валидация через gateway)
  │ circuit breaker
  │ strict validation
  │ failover gemini↔grok
        │
        ▼
llm_provider.py  (GeminiProvider / GrokProvider, ping(), build_analysis_prompt)
        │
        ▼
database.py (SQLite WAL): checks(+prompt_version/hash), whitelist, brands,
                          batch_tasks, request_cache(A.2), retry_queue(A.6)
```

## Ключевые сущности и их связи

| Сущность | Назначение | Связи |
|---|---|---|
| `checks` | История проверок; колонки A.8 (`prompt_version/hash`) + B (`ela_score/flag`, `exif_flags`, `final_score`, `score_components`, `phash`, `verdict_source`, `consensus`, `raw_model_responses`) | пишется из `/analyze`, `/analyze-deep`, батча |
| `image_hashes` | Перцептивные хэши всех изображений (B.1): fast-path вердикты, reverse search `POST /api/v1/similar` | заполняется из `/analyze`; дедупликация discovery в Block C |
| `brand_watches` | Мониторинг бренда (C.1): ключевые слова, площадки, cron-расписание, эталонные фото (base64 JSON), `next_run_at`/`last_status` | читается scheduler'ом (`services/scheduler_service.py`) |
| `discovery_listings` | Найденные карточки (C.3): UNIQUE(watch_id, url), TTL-дедупликация по вердикту | создаётся движком скана; источник дайджестов |
| `cases` / `case_status_history` / `case_comments` | Workflow кейсов (D.3): статус-машина с валидацией переходов, SLA-дедлайны, аудит и комментарии | кейсы авто-создаются из проверок с вердиктом ≠ ОРИГИНАЛ; PDF/жалобы рендерятся из кейса |
| `tenants` / `api_keys` | Мульти-тенантность (F): планы и лимиты; ключи доступа с ролями (SHA-256, per-tenant) | каждый запрос резолвится через `services/tenancy.py`; данные всех сущностей изолированы по `tenant_id` |
| `request_cache` | Идемпотентность: вердикт по `request_id` (A.2), TTL `IDEMPOTENCY_TTL_HOURS` | читается до вызова LLM, заполняется после |
| `retry_queue` | Отложенные анализы при полном отказе провайдеров (A.6) | обрабатывается `services/retry_worker.py`; результат попадает в `request_cache` |
| `CircuitBreaker` (per provider, in-process) | Размыкание после N подряд ошибок, экспоненциальное окно восстановления, half-open probe | состояние видно в `/health` и метрике `fakedetect_provider_breaker_state` |
| `TokenBucketRateLimiter` (per provider) | Превентивный троттлинг под квоту API (A.6) | стоит ПЕРЕД breaker в `analyze_resilient` |
| `AnalysisResult` (models/schemas.py) | Строгий контракт ответа LLM (A.4); graceful fallback `ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ` | валидирует каждый ответ gateway/aggregator/batch |
| `Deadline` (core/deadline.py) | Единый таймаут-бюджет всего пути запроса (A.3), contextvar | ставится в роутерах, уважается gateway |

## Поток единичного анализа (`POST /api/v1/analyze`)

1. middleware фиксирует `X-Request-ID` (или генерирует) и латентность.
2. Идемпотентность: `request_cache[request_id]` → HIT ⇒ мгновенный ответ.
3. Ставится `Deadline(request_timeout_budget_seconds)`.
4. `gateway.analyze_resilient()`:
   token bucket → circuit breaker → вызов провайдера (с быстрыми сетевыми ретраями)
   → строгая валидация `AnalysisResult` → при невалидном JSON один corrective-retry
   (модель видит свой плохой вывод) → при неудаче failover к следующему настроенному
   провайдеру (логируется каждое переключение).
5. Исходы:
   - успех → `save_check` (+ prompt fingerprint) + `cache_put_result` → 200;
   - все провайдеры недоступны (`AllProvidersDownError`) → запись в `retry_queue`,
     ответ **202** c `poll_url=/api/v1/queue/{id}`; фоновый воркер повторяет с backoff;
   - модели отвечают мусором (`AllOutputsInvalidError`) → graceful verdict
     «ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ» вместо 500;
   - исчерпан бюджет → 504 + `Retry-After`.

## Observability (A.5)

- Логи: `observability.setup_logging()`, формат `LOG_FORMAT=json` даёт структурированные
  строки со сквозным `request_id`.
- Метрики Prometheus на `/metrics`: латентности эндпоинтов (гистограмма p50/p95/p99),
  error rate по LLM-провайдерам отдельно, потреблённые токены, состояние breakers,
  размер retry-очереди.
- `/health`: БД (SELECT 1 + латентность), конфигурация каждого провайдера + состояние
  breaker'а, Playwright; `?deep=true` добавляет дешёвые REST-ping провайдеров.

## Воспроизводимость качества (A.8)

- Промпт — единственный источник истины: `llm_provider.build_analysis_prompt()`;
  версия — `PROMPT_VERSION`. Каждый сохранённый вердикт хранит версию + SHA-256 промпта.
- Golden dataset: `evals/golden_dataset/` (генерируется детерминированно).
  Обязательная проверка перед любым PR, меняющим промпт или модель:
  `python evals/run_golden_set.py --mock` (офлайн) или `--provider gemini`.

## Распределённый деплой (известное ограничение)

Breaker/token-bucket state живёт в процессе (один asyncio-loop). Для multi-worker
деплоя за балансировщиком: либо sticky-routing по провайдеру, либо перенос счётчиков
breaker'а в Redis (интерфейс `get_breaker/get_bucket` — точка замены). SQLite остаётся
ограничением для горизонтального масштаба — путь миграции на Postgres описан в README.
