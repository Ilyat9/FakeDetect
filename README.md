# FakeDetect — AI-детектор подделок

Система выявления контрафактных товаров на маркетплейсах (WB, Ozon, Яндекс Маркет). Использует Gemini 2.5 Flash Vision для визуального сравнения товаров.

> 📋 **Реестр компромиссов**: все осознанные упрощения каждого блока задокументированы
> в [COMPROMISES.md](COMPROMISES.md) — что упростили, почему, влияние и как исправить
> после стабилизации MVP. Обновляется по мере развития.


## Структура проекта

```
FakeDetect/
├── main.py                  # Сборка FastAPI-приложения (роутеры, middleware, startup)
├── server.py                # Backwards-compatible точка входа (uvicorn server:app)
├── core/
│   ├── config.py            # Settings, управление LLM-провайдерами и лимитами
│   └── security.py          # API-key авторизация (X-API-Key)
├── routers/                 # HTTP-слой (тонкие контроллеры), префикс /api/v1
│   ├── analysis.py          # /analyze, /analyze-deep, /parse-image
│   ├── batch.py             # /batch, /batch/{id}, /batch/{id}/download
│   └── data.py              # /history, /stats, /whitelist
├── services/                # Бизнес-логика
│   ├── security.py          # SSRF-защита исходящих HTTP-запросов
│   ├── browser_service.py   # Playwright headless-браузер (общий)
│   ├── marketplace_image_fetcher.py  # Извлечение фото товаров по URL
│   └── batch_service.py     # Фоновая батч-обработка + Excel-отчёт
├── aggregator.py            # Агрегатор результатов анализа изображений
├── parsers/                 # Парсеры маркетплейсов (WB, Ozon, Яндекс Маркет)
├── llm_provider.py          # Провайдеры LLM (Gemini, Grok)
├── database.py              # SQLite-слой с versioned-миграциями
├── telegram_alerts.py       # Telegram-уведомления (HTML parse_mode)
├── tests/                   # pytest: unit + integration (TestClient)
├── index.html               # Frontend
├── Dockerfile               # Multi-stage образ с Playwright Chromium
├── docker-compose.yml       # Оркестрация (+ опциональный Postgres)
└── .github/workflows/ci.yml # CI: тесты + линтер на каждый push/PR
```

## Установка

```bash
pip install -r requirements.txt
```

### Новые зависимости

- `beautifulsoup4>=4.12` — HTML парсер
- `lxml>=5.0` — XML/HTML парсер (быстрее)
- `playwright` + `playwright-stealth` — headless-браузер для глубокого анализа (`/analyze-deep`)
  и батч-обработки. **Обязательный шаг после установки:**

```bash
playwright install chromium
```

Без установленного Chromium `/analyze-deep` вернёт ошибку 501 с инструкцией по установке.

## Настройка

Создайте файл `.env` из шаблона:

```bash
cp .env.example .env
```

Добавьте API ключ:

```bash
# Для Gemini (бесплатно)
echo "GEMINI_API_KEY=ваши_ключ" >> .env

# Или для Grok (xAI)
echo "PROVIDER=grok" >> .env
echo "GROK_API_KEY=ваши_ключ" >> .env
```

Получить Gemini API ключ бесплатно: https://aistudio.google.com

### Безопасность (рекомендуется для продакшена)

| Переменная | Описание |
|---|---|
| `ALLOWED_ORIGINS` | Разрешённые CORS-источники через запятую (например `https://myapp.com`). Пусто — только same-origin. |
| `API_SECRET_KEY` | Если задан, защищённые эндпоинты (`/history`, `/stats`, `/whitelist*`) требуют заголовок `X-API-Key`. |

Также для продакшена рекомендуется reverse-proxy (nginx) с лимитом тела запроса
(`client_max_body_size 25m;`) и TLS.

## Запуск

```bash
uvicorn main:app --reload
# или через legacy-алиас: uvicorn server:app --reload
```

Откройте в браузере: http://localhost:8000

### Docker (рекомендуется для деплоя)

```bash
docker compose up --build -d
```

Образ включает Playwright Chromium; SQLite персистится в volume `app-data`
(путь настраивается через `DB_PATH`).

### Тесты

```bash
pip install -r requirements-dev.txt
pytest -v --cov=services --cov=parsers --cov=routers --cov=core
```

CI (GitHub Actions) прогоняет тесты и линтер на каждый push/PR.

## Миграции

Схема SQLite управляется versioned-миграциями в `database.py::MIGRATIONS` — они
применяются автоматически при старте приложения. Чтобы изменить схему,
добавьте новый кортеж `(version, description, statements)` в конец списка;
уже применённые миграции никогда не редактируются.

**Путь на Postgres для продакшена:** SQLite не поддерживает многопроцессный
`uvicorn --workers N` без блокировок записи. При росте нагрузки переключитесь
на `SQLAlchemy[asyncio]` + `asyncpg` + Alembic (сервис Postgres уже подготовлен
в docker-compose.yml как закомментированный профиль).

## Версионирование API

Все эндпоинты доступны под префиксом `/api/v1` (например `/api/v1/analyze`).
Неверсионированные пути (`/analyze`, `/history`, ...) сохранены как deprecated
на grace-period и будут удалены в будущем мажорном релизе. `/health` и статика
не версонируются.


## Как использовать

1. Вставьте API ключ в файл `.env`
2. Выберите режим ввода: загрузить фото или вставить URL маркетплейса
3. Загрузите эталонное фото и фото с маркетплейса
4. Нажмите «АНАЛИЗ»
5. Результат появится через 3-5 секунд

## Эндпоинты API

### Базовые эндпоинты
- `GET /` — главная страница (HTML)
- `GET /health` — проверка статуса

### Анализ изображений
- `POST /analyze` — анализ изображений (парсинг + сравнение)
- `POST /analyze-deep` — глубокий анализ (парсинг маркетплейса + агрегация результатов по всем фото)
- `POST /parse-image` — только парсинг URL и извлечение изображений

### Батч-обработка
- `POST /batch` — пакетная обработка множества товаров
  - Загружает файл с парами (URL, эталонное фото)
  - Обрабатывает все товары асинхронно
  - Возвращает результаты всех анализов

## Технологии

- **Backend**: FastAPI, Uvicorn, httpx, BeautifulSoup4
- **Frontend**: HTML5, CSS3, Vanilla JS
- **AI Models**:
  - Gemini 2.5 Flash Vision (Google)
  - Grok 2 Vision (xAI)
- **Features**:
  - Мульти-маркетплейс парсинг (Wildberries, Ozon, Яндекс Маркет)
  - Автоматическое извлечение карточек и отзывов с фото
  - Параллельный анализ изображений с rate limiting
  - Батч-обработка множества товаров (Excel-импорт)
  - Retry logic с exponential backoff
  - CORS для фронтенда
  - Pydantic Settings для конфигурации
  - Агрегация результатов от нескольких моделей/парсеров
  - История проверок в SQLite
  - Whitelist для исключённых брендов

## 📈 Дашборд ROI-метрик и экспорт (Block E)

То, что продаёт подписку руководству: измеримая польза, а не «детектор картинок».

### API (`/api/v1/analytics/*`, viewer+, tenant-scoped)
| Эндпоинт | Метрика |
|---|---|
| `/timeseries?granularity=day\|week\|month&days=&brand=` | Динамика вердиктов по периодам |
| `/top-sellers?limit=&days=` | Топ продавцов по подтверждённым нарушениям |
| `/revenue?days=&brand=` | Оценка защищённой выручки + **явный дисклеймер** |
| `/timing` | Time-to-detection / time-to-resolution |
| `/summary` | Всё разом для дашборда |
| `/export.pdf`, `/export.pptx` | Отчёт для руководства (PDF; PPTX-дека) |

### Фронтенд
Вкладка **«📊 Дашборд»** в интерфейсе: KPI-карточки (проверки, подделки,
защищённая выручка, TTD/TTR), stacked-график динамики (Chart.js), таблица топа
нарушителей, экспорт в PDF/PPTX одной кнопкой.

### Методология
- **Защищённая выручка** = подтверждённые подделки за период × средняя цена
  оригинала бренда за тот же период. Это оценка спроса, который мог уйти к
  контрафакту, — в ответе API и отчётах всегда присутствует дисклеймер.
- **Time-to-detection** измеряется для карточек, найденных Discovery-мониторингом
  (от первого появления в выдаче до вердикта); для ручных проверок дата публикации
  неизвестна.
- **Time-to-resolution** — от создания кейса до перехода в CLOSED (по журналу
  статусов).

## 🏢 Мульти-тенантность, роли и биллинг (Block F)

### Тенанты и изоляция (F.1)
Каждая сущность (checks, whitelist, brands, batch_tasks, brand_watches,
discovery_listings, image_hashes, cases) несёт `tenant_id`; все списочные запросы
фильтруются по нему на уровне SQL. Компромисс изоляции зафиксирован
в COMPROMISES.md (F-C1: фильтрация в запросах; Row-Level Security — после
миграции на Postgres).

### Аутентификация и роли (F.2)
- Ключи: `X-API-Key` → SHA-256 → таблица `api_keys` (per-tenant, роль, active).
- Легаси-мастер-ключ (`API_SECRET_KEY`) продолжает работать = owner Default-тенанта.
- **Open mode**: если `API_SECRET_KEY` не задан — весь трафик мапится на Default
  tenant с правами owner (локальная разработка/фронтенд/тесты без ключей).
- Роли: `owner > admin > analyst > viewer`, плюс спец-роль `legal`
  (только статусы кейсов + evidence-пакеты; без сырых LLM-ответов и конфигурации).

| Действие | Минимальная роль |
|---|---|
| Чтение history/stats/cases/evidence-pdf/complaint | viewer (+legal для кейсов) |
| Запуск /analyze, /analyze-deep, /batch, reverse search | analyst |
| Переходы статусов, комментарии, assign, bulk | analyst |
| Whitelist write, brand watches CRUD/run-now, /cases/overdue | admin |
| Управление API-ключами, биллинг-план | owner |

### Лимиты тарифов (F.3)
`tenants.max_checks_per_month / max_watches / max_users`. При превышении —
**402 Payment Required** с телом `{error, limit, plan, used, max, upgrade_hint}`.
Проверка квоты стоит до дорогого LLM-вызова; кэш-реплеи (идемпотентность) квоту
не расходуют.

### Биллинг (F.4)
- `POST /api/v1/billing/webhook/stripe` — проверка HMAC подписи `Stripe-Signature`
  (`BILLING_STRIPE_WEBHOOK_SECRET`, fail-closed) + анти-replay окно 5 минут;
- `POST /api/v1/billing/webhook/yookassa` — общий секрет в `X-Yookassa-Secret`;
- события (нормализованный контракт): `subscription_activated {plan}` /
  `subscription_cancelled` → применение лимитов плана / деактивация тенанта;
- `POST /api/v1/billing/plans/{tenant_id}` — ручная смена плана (owner своего
  тенанта). Планы: free 100 проверок/2 watch/3 юзера · pro 2000/10/10 ·
  business 20000/50/50.

### Партнёрский REST API (F.5)
Отдельный контур `/api/v1/partner/*`: только по ключам (open-mode НЕ действует),
строгий per-key rate limit (`PARTNER_RATE_LIMIT_PER_MIN`, по умолчанию 30/мин → 429),
минимальная поверхность:

```
POST /api/v1/partner/checks          анализ пары изображений (квотируемый)
GET  /api/v1/partner/checks/{rid}    вердикт по request_id (tenant-scoped)
GET  /api/v1/partner/stats           статистика + использование квоты
```

Swagger/OpenAPI — стандартный `/docs` FastAPI.

## ⚖️ Evidence Package и Workflow кейсов (Block D)

### Кейсы и статус-машина (D.3)
Каждая проверка с вердиктом ≠ «ОРИГИНАЛ» автоматически открывает **кейс**
(идемпотентно, один check = один case) и проходит по статусам:

```
DETECTED → UNDER_REVIEW → CONFIRMED_FAKE / FALSE_POSITIVE →
COMPLAINT_FILED → LISTING_REMOVED → CLOSED   (+ REQUIRES_MANUAL_REVIEW)
```

- Недопустимые переходы отклоняются с объяснением (`400` + список разрешённых).
- Каждый шаг пишется в `case_status_history` (кто/когда/комментарий) — полный аудит.
- Комментарии сотрудников: `case_comments`.
- Ответственный: `POST /cases/{id}/assign`.
- **SLA-таймеры**: на каждый статус — свой лимит часов (DETECTED 24ч, UNDER_REVIEW 72ч,
  COMPLAINT_FILED 168ч…); scheduler раз в 30 минут проверяет просрочки и шлёт
  Telegram-эскалацию ответственному/руководителю (не чаще раза в 12ч на кейс).
- **Bulk-операции**: `POST /cases/bulk-transition` — массовый перевод статуса,
  например все кейсы одного продавца → COMPLAINT_FILED.

### Evidence Package — PDF (D.1)
`GET /api/v1/cases/{id}/evidence-pdf` генерирует юридически ориентированный отчёт:

1. реквизиты кейса (бренд, URL, продавец, вердикт, время),
2. сравнение эталон vs подозрительный side-by-side,
3. скриншот карточки на момент проверки (best-effort; если браузер недоступен в
   момент проверки — делается при генерации PDF),
4. таблица признаков + форензик-сигналы (ELA, pHash, EXIF-флаги, final_score),
5. история цены товара по всем проверкам этого URL,
6. **цепочка хранения доказательств**: SHA-256 каждого файла-артефакта,
   зафиксированные системой при сохранении.

Артефакты (reference/suspect/meta/screenshot) пишутся в `EVIDENCE_DIR/{check_id}/`,
манифест дублируется в колонку `checks.evidence_files`.

### Шаблоны жалоб (D.2)
`GET /api/v1/cases/{id}/complaint?marketplace=WB|Ozon|Yandex` — готовый текст жалобы,
автозаполненный данными кейса и доказательствами (Jinja2-шаблоны в
`templates/complaints/`, легко править без кода). Публичного API подачи брендовых
жалоб у площадок нет — текст копируется в форму площадки вручную; цель — ускорить
ручной шаг до ~30 секунд, а не имитировать интеграцию.

## 🤖 Автономный мониторинг — Discovery Engine (Block C)

Система сама ищет подозрительные карточки по бренду: пользователю больше не нужно
приносить ссылки вручную.

### Как работает
1. **Brand Watch** (`POST /api/v1/watches`): бренд + ключевые слова + площадки
   (WB/Ozon/Yandex) + эталонное фото + cron-расписание скана (например `0 7 * * *`).
2. **Scheduler** внутри FastAPI-процесса (APScheduler): каждую минуту проверяет,
   какие watch'и «созрели», и запускает сканы в фоне; расписание живёт в БД и
   переживает рестарты.
3. **Discovery-парсеры** (C.2): WB — публичный JSON search API (без браузера);
   Ozon/Яндекс — Playwright с деградацией до httpx (partial results).
4. **Дедупликация** (C.3): найденная карточка (`discovery_listings`, уникально
   watch+URL) повторно анализируется только по истечении TTL вердикта:
   ОРИГИНАЛ → 7 дней, ПОДОЗРИТЕЛЬНО → 2 дня, ПОДДЕЛКА → 1 день (`RECHECK_*`);
   плюс pHash fast path из блока B не тратит LLM на уже виденные фото.
5. **Анализ**: каждая новая карточка проходит тот же пайплайн, что `/analyze`
   (форензика → LLM → консенсус → композитный счёт) без участия человека.
6. **Дайджесты** (C.4): находки копятся и отправляются сводкой в Telegram раз в
   `digest_interval_hours` (per-watch), вместо алерта на каждую карточку;
   email-дайджест — заготовка (SMTP-провайдер на выбор).

### API
```
POST   /api/v1/watches                    создать watch (multipart: + reference image)
GET    /api/v1/watches                    список
GET    /api/v1/watches/{id}               статус (last_run_at, next_run_at, last_status)
GET    /api/v1/watches/{id}/listings      найденные карточки с вердиктами
POST   /api/v1/watches/{id}/run-now       внеплановый скан немедленно
DELETE /api/v1/watches/{id}               удалить watch и его листинги
```

## 🧠 Многоуровневый движок детекции (Block B)
Проверка больше не «один вызов LLM». Пайплайн `/api/v1/analyze`:

```
suspect.png ──► pHash ──дубликат?──да──► мгновенный вердикт (verdict_source=phash_match)
                   │                              без затрат на LLM
                   ▼ нет
              ELA + EXIF ──► объективные форензик-сигналы (в ответ и в историю)
                   ▼
              LLM Vision (circuit breaker + failover) ──► строгая валидация JSON
                   ▼ confidence ∈ [40..70]?
              Multi-model consensus: второй провайдер параллельно
                   ▼
              Композитный счёт final_score = Σ(w·s)/Σw + разбивка «почему столько»
```

### pHash fast path (B.1)
Каждое изображение получает перцептивный хэш; если в базе уже есть классифицированное
изображение с хэмминговым расстоянием ≤ `PHASH_HAMMING_THRESHOLD` (по умолчанию 8 из 64 бит),
вердикт переиспользуется мгновенно — поле `verdict_source` будет `"phash_match"`.
Повторить анализ принудительно можно заголовком `X-Force-Recheck: true`.

### ELA и EXIF (B.2)
- `ela_score`/`ela_flag` — Error Level Analysis: пересжатие JPEG с известным качеством,
  статистика ошибки. Аномально высокая локальная ошибка → признак склейки/ретуши;
  добавляется в `indicators` как независимый сигнал-доказательство.
- `exif_flags` — отсутствие EXIF у «живого» фото, дата съёмки в будущем, следы
  редакторов (Photoshop/GIMP/Lightroom…) — каждый флаг виден в indicators.

### Multi-model consensus (B.3)
Если первый провайдер вернул **пограничную уверенность** (`CONSENSUS_CONFIDENCE_LOW..
HIGH`, по умолчанию 40–70), автоматически запрашивается второй провайдер:
- **verdicts совпали** → итоговая уверенность = среднее + 10 (максимум 99), `consensus: "agreement"`;
- **мнения разошлись** → автоматический вердикт НЕ выдаётся: статус становится
  «ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ», оба сырых ответа сохраняются в `raw_model_responses`
  (и в колонку `raw_model_responses` в БД) для аудита, `consensus: "disagreement"`;
- второй провайдер недоступен → остаётся вердикт первого, `consensus: "second_opinion_unavailable"`.

> Это фича прозрачности, а не баг: часть пограничных кейсов сознательно уходит человеку.

### Объяснимый композитный вердикт (B.4)
`final_score = Σ(wᵢ·sᵢ)/Σwᵢ` только по доступным сигналам (недостающие исключаются,
веса перенормируются). Каждый сигнал нормирован в шкалу «подлинности» 0–100:

| Сигнал | Нормировка | Вес по умолчанию |
|---|---|---|
| `llm_confidence` | как есть | 0.45 |
| `phash_similarity` | сходство с эталоном | 0.25 |
| ELA | 100 − ela_score | 0.15 |
| EXIF | 100 − 20×(число red flags) | 0.05 |
| price_ratio | линейно: ≤0.2→0 … ≥0.8→100 | 0.10 |

Веса — в конфиге (`W_*`, `PRICE_FLOOR/CEILING`). Ответ API содержит `final_score` и
`score_components` с raw-значением и вкладом каждого сигнала — решение объяснимо,
как в кредитном скоринге, а не «чёрный ящик одной модели».

## 🛡️ Надёжность и SLO (Block A)

Продакшен-механизмы (подробности — в [ARCHITECTURE.md](ARCHITECTURE.md), изменения — в
[CHANGELOG.md](CHANGELOG.md)):

| Механизм | Что даёт | Конфиг |
|---|---|---|
| Circuit breaker на провайдера | 5 ошибок подряд → провайдер временно исключается, трафик автоматически идёт на второй (gemini↔grok) | `CB_*` |
| Идемпотентность | повтор `/analyze` с тем же `X-Request-ID` возвращает кэш — LLM не оплачивается дважды | `IDEMPOTENCY_TTL_HOURS` |
| Единый timeout budget | весь путь запроса укладывается в SLA; иначе 504 + Retry-After | `REQUEST_TIMEOUT_BUDGET_SECONDS` |
| Строгая валидация LLM | невалидный JSON → 1 corrective retry → вердикт «ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ», не 500 | — |
| Retry queue | все провайдеры лежат → 202 + polling `/api/v1/queue/{id}`, воркер доигрывает сам | `RETRY_QUEUE_*` |
| Token bucket | превентивный троттлинг под квоту API, без 429 постфактум | `RL_CAPACITY`, `RL_REFILL_RATE` |
| Observability | JSON-логи с request_id, `/metrics` (Prometheus), детальный `/health` | `LOG_FORMAT` |

**SLO (заявленные цели; замеряются locust-сценариями из `loadtests/`):**

| Метрика | Цель |
|---|---|
| Успешность единичного анализа (без учёта недоступности внешних API) | ≥ 99.9% |
| Латентность `POST /api/v1/analyze-deep` при 20 параллельных пользователях | p95 < 8 с |
| Латентность `GET /health`, `/api/v1/history` | p95 < 100 мс |
| Время реакции breaker'а на отказ провайдера | ≤ N=5 последовательных ошибок |

Фактические цифры после прогонов фиксируйте здесь: _заполните после первого прогона
`locust --headless -u 20 -r 2 -t 60s` на целевом железе_.

## 🗺️ Roadmap

### v0.2 — Фундамент
- [x] Docker + docker-compose для удобного запуска в одной команде
- [x] Юнит- и интеграционные тесты (pytest) + CI

### v0.3 — Масштабирование
- [ ] Поддержка Авито и AliExpress
- [ ] Telegram-бот интерфейс: отправил ссылку — получил результат
