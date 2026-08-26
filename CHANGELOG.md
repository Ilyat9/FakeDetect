# Changelog

## [3.4.0] — 2026-08-26 — Block D: Evidence Package и Workflow кейсов

### D.3 Workflow / статус-машина
- Таблицы `cases` (+SLA-дедлайны, ответственный), `case_status_history` (аудит),
  `case_comments`.
- Автосоздание кейса для каждой проверки с вердиктом ≠ ОРИГИНАЛ (идемпотентно).
- Явная карта переходов `CASE_TRANSITIONS`: DETECTED → UNDER_REVIEW →
  CONFIRMED_FAKE/FALSE_POSITIVE → COMPLAINT_FILED → LISTING_REMOVED → CLOSED
  (+ REQUIRES_MANUAL_REVIEW); недопустимые переходы — 400 с объяснением.
- SLA-таймеры per-status + эскалация в Telegram раз в 30 минут scheduler'ом
  (троттлинг 12ч/кейс); эндпоинт `/cases/overdue`.
- Bulk-переходы (`POST /cases/bulk-transition`), назначение ответственного,
  комментарии с историей.

### D.1 Evidence Package (PDF)
- `services/evidence_store.py`: артефакты проверки (эталон, подозрительный, meta,
  best-effort full-page скриншот) в `EVIDENCE_DIR/{check_id}/` + манифест SHA-256,
  зеркалируемый в колонку `checks.evidence_files` (миграция №3).
- `GET /api/v1/cases/{id}/evidence-pdf` (reportlab): реквизиты кейса, side-by-side
  сравнение, скриншот, таблица признаков и форензик-сигналов, история цены URL,
  цепочка хранения SHA-256.

### D.2 Шаблоны жалоб
- `GET /api/v1/cases/{id}/complaint?marketplace=WB|Ozon|Yandex`: готовый к копированию
  текст жалобы из Jinja2-шаблонов `templates/complaints/*.txt.j2`, автозаполнение
  данными кейса и доказательствами; неизвестная площадка → generic-шаблон.
- Полная автоматизация подачи невозможна (нет публичного API у площадок) — цель:
  ускорить ручной шаг.

### Прочее
- `/analyze` принимает поле `seller` (попадает в checks/cases/PDF/жалобы).
- Новый **COMPROMISES.md** — реестр осознанных компромиссов A/B/C/D (что упростили,
  почему, влияние, план исправления после MVP); закреплён в README.

### Тесты
- +10 тестов Блока D: автосоздание кейса + manifest SHA-256, полная валидная цепочка
  переходов и терминальный lock, отказ невалидного перехода, комментарии/assignee,
  bulk (включая отчёт по неуспешным), SLA overdue + эскалация с троттлингом,
  генерация PDF (%PDF-магия), жалобы для трёх площадок + generic-fallback,
  ОРИГИНАЛ не открывает кейс. Всего 93 passed.

## [3.3.0] — 2026-08-26 — Block C: автономный мониторинг (Discovery Engine)

### C.1 Brand Watch + scheduler
- Таблица `brand_watches`: бренд, ключевые слова, площадки, cron-расписание,
  эталонные изображения, `next_run_at`/`last_status`/`last_digest_at`.
- `services/scheduler_service.py`: APScheduler внутри FastAPI с одним tick-job'ом —
  расписание живёт в БД и переживает рестарты; падение одного watch'а не влияет
  на остальные (`_guarded_run`).
- CRUD API `/api/v1/watches` (+ `/{id}/run-now`, `/{id}/listings`), cron валидируется
  через APScheduler CronTrigger.

### C.2 Discovery-парсеры
- WB: публичный JSON search API (`search.wb.ru`) — без браузера, устойчиво.
- Ozon / Яндекс.Маркет: Playwright-страница с graceful деградацией до httpx
  link-extraction (partial results), общий браузер на весь скан.

### C.3 Дедупликация
- `discovery_listings` c UNIQUE(watch_id, url); повторный анализ только после TTL:
  ОРИГИНАЛ 7 дней / ПОДОЗРИТЕЛЬНО 2 дня / ПОДДЕЛКА 1 день (настраивается);
  плюс pHash fast path блока B отсекает уже классифицированные фото без LLM.
  Ошибки dedup-check'а fail-open в сторону повторного анализа.

### C.4 Связка с движком анализа + дайджесты
- Каждая новая карточка проходит полный пайплайн `/analyze` (форензика → LLM →
  консенсус → композитный счёт) автоматически; результаты попадают в checks,
  image_hashes и listings.
- Дайджест находок раз в `digest_interval_hours` per-watch в Telegram
  (email — заготовка), вместо спама алертом на каждую находку.

### Инфраструктура
- Зависимость: `apscheduler>=3.10,<4`.
- Scheduler стартует/останавливается вместе с приложением (startup/shutdown).

### Тесты
- +9 тестов Блока C: cron next-run (+fallback), TTL-дедупликация по вердикту,
  уникальность listing'ов, get_due_watches, WB search API parser (мок),
  полный цикл скана e2e (поиск→анализ→TTL skip→дайджест) и CRUD API + run-now.
  Всего 83 passed.

## [3.2.0] — 2026-08-26 — Block B: форензика и многоуровневый движок детекции

### B.1 Perceptual hashing
- `forensics/phash.py`: pHash (imagehash, 8x8) каждого изображения.
- Таблица `image_hashes` (+ индексы); поиск ближайшего классифицированного хэша по
  хэмминговому расстоянию ≤ `PHASH_HAMMING_THRESHOLD`.
- **pHash fast path** в `/analyze`: дубликат → мгновенный вердикт с
  `verdict_source="phash_match"` и нулевыми затратами на LLM (`X-Force-Recheck` — форс).
- **Reverse image search**: `POST /api/v1/similar` (под защитой API-ключа) — все проверки
  с похожими изображениями (JOIN к checks: url/brand/marketplace/verdict).

### B.2 ELA + EXIF
- `forensics/ela.py`: Error Level Analysis (пересжатие JPEG q=`ELA_QUALITY`, RMS +
  99.9-перцентиль локальной ошибки) → `ela_score`, `ela_flag`, `max_error`;
  при флаге в indicators добавляется объективный сигнал «следы редактирования».
- `forensics/exif.py`: отсутствие EXIF, дата съёмки в будущем, следы редакторов —
  red flags в indicators; сохраняются колонкой `exif_flags`.

### B.3 Multi-model consensus
- Пограничная уверенность первого провайдера (band `CONSENSUS_CONFIDENCE_*`, 40–70)
  запускает второго провайдера через `asyncio.gather`. Правила:
  совпадение → confidence = avg+10; расхождение → «ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ»;
  недоступен второй → вердикт первого. Оба сырых ответа сохраняются
  (`raw_model_responses` в ответе API и в БД) для аудита. Логика задокументирована
  в README («Многоуровневый движок детекции»).

### B.4 Объяснимая формула вердикта
- `core/verdict_engine.py`: `final_score = Σ(w·s)/Σw` по доступным сигналам
  (llm_confidence, phash_similarity, ELA, EXIF, price_ratio), веса в конфиге,
  перенормировка при отсутствии сигналов. Ответ API содержит `score_components`
  с разбивкой вкладов («почему именно столько»). LLM сохраняет ярлык вердикта,
  форензика модулирует уверенность (±15 max, `adjust_confidence_with_forensics`).

### Инфраструктура
- Миграция №2: форензик-колонки в `checks`. `save_check` пишет полный набор сигналов.
- Зависимость: `imagehash>=4.3` (+scipy транзитивно).

### Тесты
- +17 тестов Блока B: pHash/ELA/EXIF unit, roundtrip hash-индекса, математика
  композитного счёта (полная разбивка, перенормировка, границы price-ratio),
  правила консенсуса (agreement/disagreement/outside-band/second-down/no-provider),
  e2e через API: обогащение ответа, pHash fast-path без повторного LLM-вызова,
  reverse search. Всего 74 passed.

## [3.1.0] — 2026-08-26 — Block A: надёжность уровня «ноль незапланированных сбоев»

### A.1 Circuit breaker + failover
- `core/resilience.py`: CircuitBreaker на каждого LLM-провайдера (N ошибок подряд →
  размыкание, экспоненциально растущее окно восстановления с jitter, half-open probe).
- `core/llm_gateway.py::analyze_resilient()` — автоматический failover gemini↔grok
  без участия пользователя; каждое переключение логируется и инкрементирует метрику.

### A.2 Идемпотентность
- Таблица `request_cache` (уникальный PK `request_id`, TTL). `/analyze` принимает
  `X-Request-ID` (заголовок или форма), повторный запрос возвращает кэшированный
  вердикт (`X-Cache: HIT`) — LLM не вызывается второй раз, деньги не тратятся.

### A.3 Единый timeout budget
- `core/deadline.py`: дедлайн всего пути запроса (HTTP → препроцессинг → LLM → БД),
  передаётся через contextvar; при исчерпании — явный 504 с `Retry-After`.

### A.4 Строгая валидация ответов LLM
- `models/schemas.py`: Pydantic-модель `AnalysisResult` (Enum вердиктов, confidence
  0–100, indicators со статусами ok/warn/fail). Каждый ответ всех путей анализа
  (`/analyze`, aggregator, batch) валидируется; при невалидном JSON — один corrective
  retry, где модель видит свой некорректный вывод; затем graceful degradation в
  вердикт «ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ» вместо 500.

### A.5 Observability
- Структурированные JSON-логи (`LOG_FORMAT=json`) со сквозным request_id.
- Prometheus `/metrics`: латентности эндпоинтов (p50/p95/p99), error rate провайдеров
  отдельно от приложения, потреблённые токены (usage из Gemini/Grok API), состояния
  breakers, размер retry-очереди.
- `/health` теперь детальный: БД (SELECT 1 + latency), каждый LLM-провайдер
  (конфигурация, состояние breaker'а, опциональный REST-ping через `?deep=true`),
  Playwright. Контракт изменён: `status` = ok|degraded.

### A.6 Graceful degradation
- Playwright/браузер недоступен → `/analyze-deep` деградирует до httpx-парсинга с
  явным `partial_data=true` + `partial_reason` вместо 501/падения.
- Все провайдеры недоступны → запрос ставится в `retry_queue`, клиент получает **202**
  c `poll_url`; фоновый воркер (`services/retry_worker.py`) повторяет с экспоненциальным
  backoff, результат появляется в `GET /api/v1/queue/{request_id}`.
- Token bucket на стороне приложения (`RL_CAPACITY`/`RL_REFILL_RATE`) — превентивный
  троттлинг под квоту вместо 429 постфактум.

### A.7 Нагрузочное тестирование
- `loadtests/locustfile.py` (+ README): сценарии single-analyze/health/history;
  заявленный SLO зафиксирован в README («Надёжность и SLO»).

### A.8 Версионирование промптов и golden dataset
- Промпт вынесен в `llm_provider.build_analysis_prompt()`, версия `PROMPT_VERSION`;
  каждый сохранённый вердикт хранит `prompt_version` + `prompt_hash` (миграция №1).
- `evals/golden_dataset/` (детерминированные фикстуры) + `evals/run_golden_set.py`
  (офлайн mock-режим и реальный провайдер) — обязательная регрессионная проверка
  качества перед изменением промпта/модели.

### Тесты
- +16 новых тестов: resilience (breaker/bucket/deadline), gateway (failover,
  corrective-retry, circuit-open), идемпотентность+202-очередь+воркер, /metrics,
  golden-set. Всего 55 passed.

## [3.0.0] — 2026-08-26

### Architecture
- **3.1** server.py (661 строка) разделён на слои: `main.py` (сборка приложения),
  `core/` (config, security), `routers/` (analysis, batch, data), `services/batch_service.py`.
  `server.py` оставлен как back-compat шим (`uvicorn server:app` продолжает работать).
- **3.4** Добавлен набор тестов pytest: unit (SSRF, БД+миграции, агрегатор, Telegram,
  парсеры) и integration через TestClient, включая полный батч-цикл с мок-LLM
  и регрессионный тест Excel-выгрузки. CI workflow (GitHub Actions): тесты с
  coverage + ruff на каждый push/PR.
- **3.5** Dockerfile (multi-stage, Playwright Chromium в образе), docker-compose.yml
  с персистентным volume для БД и опциональным профилем Postgres.
- **3.3** Versioned-migration runner в `database.py` (таблица schema_migrations),
  `DB_PATH` настраивается через env; задокументирован путь миграции на
  Postgres (SQLAlchemy async + asyncpg + Alembic).
- **4.8** Версионирование API: все эндпоинты доступны под `/api/v1`, легаси-пути
  сохранены на grace-period; фронтенд переключён на версонируемые пути.

## [2.1.0] — 2026-08-26

### Fixed (критические баги)
- **1.1/1.10** Батч-обработка: статус завершения синхронизирован (`completed`), реализована реальная
  генерация Excel-отчёта и эндпоинт `GET /batch/{task_id}/download`; фронтенд скачивает файл по завершении.
- **1.2** `parse_gemini`/`parse_grok` объединены в единую функцию `parse_marketplace_image`
  в новом модуле `services/marketplace_image_fetcher.py`.
- **1.3** `/analyze-deep`: провайдер больше не захардкожен, добавлен параметр `provider_name`,
  ключ подбирается через общую функцию `get_api_key_for_provider()`.
- **1.4** Устранён race condition с `temp_reference.png` — эталон передаётся байтами в памяти.
- **1.5** `/analyze-deep` запускает headless-браузер (Playwright) для Ozon/Yandex/WB-отзывов;
  при отсутствии Playwright возвращается явная ошибка 501 вместо тихого нулевого результата.
- **1.6** WB: таблица диапазонов vol→basket, параллельный перебор basket-серверов с ранним отбоем,
  кэш vol→basket, актуальный API v2 с заголовками Origin/Referer и обработкой 429.
- **1.7** Задачи батча перенесены из памяти в таблицу `batch_tasks` (SQLite), добавлена очистка старше 7 дней.
- **1.8** `task_id` теперь `uuid4()` (непредсказуем, защищает от перебора).
- **1.9** В батч-режиме сначала извлекается реальное фото товара (og:image/CDN), скриншот — fallback.

### Security
- **2.1** Устранены XSS на фронтенде: все пользовательские/LLM-данные экранируются через `escapeHtml()`.
- **2.2** CORS: явный список origins через `ALLOWED_ORIGINS`, `allow_credentials=False`.
- **2.3** API-key авторизация (`X-API-Key`) для `/history`, `/stats`, `/whitelist*` при заданном `API_SECRET_KEY`.
- **2.4** SSRF-защита: whitelist доменов + DNS-проверка приватных IP + контроль редиректов и размера
  (`services/security.py`), используется во всех исходящих запросах по пользовательским URL.
- **2.5** Pydantic Settings: чистые дефолты, `field_validator` для PROVIDER, секреты в `SecretStr`.
- **2.6** Лимиты загрузки файлов: 15 МБ изображения / 25 МБ Excel (HTTP 413).
- **2.7** Все `print()` заменены на `logging`, единая конфигурация логирования.
- **2.8** Telegram-алерты переведены на `parse_mode="HTML"` с `html.escape()`.

### Architecture / мелкие исправления
- **3.9** `retry_on_failure` ретраит только сетевые ошибки, добавлен jitter.
- **3.10** Фронтенд использует относительные пути (same-origin) вместо хардкода `localhost:8000`.
- **3.11** Пагинация `offset`/`total` в `/history`.
- **4.1** `add_to_whitelist` возвращает реальный `lastrowid`.
- **4.3** Убраны дублирующиеся локальные импорты.
- **4.4** Магические числа агрегатора вынесены в именованные константы.
- **4.5** Единый источник истины по поддерживаемым маркетплейсам (`parsers/base.py::SUPPORTED_MARKETPLACES`).
- **4.7** `provider_name` валидируется через `ProviderType` (422 при неверном значении).
- Добавлены WAL-режим и индексы SQLite; Playwright/playwright-stealth включены в requirements.txt.

### Остаётся техническим долгом
- Полное разделение server.py на routers/services (частично сделано), Alembic-миграции,
  переход на Postgres для multi-worker деплоя.
- Тесты (pytest + CI), Docker/docker-compose, версионирование API `/api/v1`.
