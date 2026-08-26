<div align="center">

# FakeDetect

**Платформа защиты бренда от контрафакта на маркетплейсах** (Wildberries, Ozon, Яндекс Маркет).

[![CI](https://github.com/Ilyat9/FakeDetect/actions/workflows/ci.yml/badge.svg)](https://github.com/Ilyat9/FakeDetect/actions/workflows/ci.yml)
[![Frontend CI](https://github.com/Ilyat9/FakeDetect/actions/workflows/frontend-ci.yml/badge.svg)](https://github.com/Ilyat9/FakeDetect/actions/workflows/frontend-ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-3.1.0-009485)
![React](https://img.shields.io/badge/frontend-React_19_·_TS_strict-61dafb)
![Tests](https://img.shields.io/badge/tests-178_passing-brightgreen)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

## Зачем

Бренды теряют выручку из-за контрафакта, а ручной поиск подделок не масштабируется: карточек тысячи,
продавцы переезжают между площадками, для жалобы нужны доказательства, которые после факта уже не собрать.

**FakeDetect** закрывает весь цикл: находит подозрительные карточки по расписанию, выносит вердикт
с композитным скорингом (pHash + ELA/EXIF + консенсус LLM-визуальных моделей), ведёт кейс до закрытия,
собирает evidence-PDF с цепочкой доказательств и показывает руководителю защищённую выручку.

| | |
|---|---|
| Тесты | 178: 113 backend (pytest) + 65 frontend (Vitest/RTL/MSW), включая контрактные |
| API | 46 эндпоинтов `/api/v1` + OpenAPI (`/docs`) |
| Хранилище | 15 таблиц, SQLite с versioned-миграциями (слой готов под Postgres) |

## Скриншоты

| Дашборд | Вердикт |
|---|---|
| ![Дашборд](docs/screenshots/dashboard.png) | ![Вердикт](docs/screenshots/verdict.png) |
| **Канбан кейсов** | **Brand watch** |
| ![Кейсы](docs/screenshots/cases.png) | ![Watches](docs/screenshots/watches.png) |

<details>
<summary>Как снять скриншоты</summary>

```bash
docker compose up --build   # frontend на http://localhost:8080
# страницы: / -> dashboard.png · /analyze -> verdict.png ·
#           /cases -> cases.png (вид «Канбан») · /watches -> watches.png
```

</details>

## Быстрый старт

**Backend**

```bash
pip install -r requirements.txt
playwright install chromium        # для /analyze-deep и батчей
cp .env.example .env               # укажите GEMINI_API_KEY или GROK_API_KEY
uvicorn main:app --reload          # http://localhost:8000, Swagger — /docs
```

**Frontend (SPA)**

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173, /api проксируется на :8000
```

**Docker (одной командой)**

```bash
docker compose up --build          # backend :8000, frontend :8080
```

Ключ Gemini — бесплатно на <https://aistudio.google.com>.

## Архитектура

```
FakeDetect/
├── main.py, server.py        # Сборка FastAPI-приложения; legacy-точка входа
├── core/                     # Конфигурация, security, circuit breaker, метрики
├── routers/                  # HTTP-слой (/api/v1): analysis, batch, data, cases,
│                             #   watches, analytics, billing, partner, system
├── services/                 # Бизнес-логика: tenancy, resilience, discovery,
│                             #   evidence, batch, scheduler, retry worker
├── parsers/                  # Парсеры WB / Ozon / Яндекс Маркет
├── forensics/                # pHash, ELA, EXIF-анализ изображений
├── aggregator.py             # Композитный вердикт (взвешенная сумма сигналов)
├── llm_provider.py           # Провайдеры: Gemini / Grok Vision
├── database.py               # SQLite + versioned-миграции (15 таблиц)
├── tests/                    # pytest: unit + integration
├── frontend/                 # SPA: React 19 + TS strict, Feature-Sliced, TanStack
├── docs/                     # ARCHITECTURE, COMPROMISES, CHANGELOG, DEPLOY, QUICKSTART,
│                             #   architecture-decisions, screenshots
├── Dockerfile                # Multi-stage образ (Playwright Chromium)
└── docker-compose.yml        # backend + frontend (nginx, /api same-origin)
```

Ключевые решения (почему свой circuit breaker, нормализованные вебхуки, explainable scoring)
— [docs/architecture-decisions.md](docs/architecture-decisions.md).
Осознанные упрощения — [docs/COMPROMISES.md](docs/COMPROMISES.md).

## Возможности

**Детекция.** Композитный вердикт из нормированных сигналов: LLM-confidence (0.45), pHash (0.25),
ELA (0.15), price ratio (0.10), EXIF (0.05). Пограничная уверенность (40–70%) запускает второго
провайдера; при расхождении мнений вердикт уходит человеку, оба ответа сохраняются для аудита.
Каждый сигнал виден в API и в UI («почему такой вердикт») — решение объяснимо, а не «чёрный ящик».

**Автономный мониторинг.** Brand watches по cron-расписанию ищут новые карточки по бренду,
дедуплицируют по URL/SKU и прогоняют через детекцию; дайджесты в Telegram.

**Кейсы.** Проверка с вердиктом ≠ «оригинал» автоматически открывает кейс:
`DETECTED → UNDER_REVIEW → CONFIRMED_FAKE/FALSE_POSITIVE → COMPLAINT_FILED → LISTING_REMOVED → CLOSED`.
Валидация переходов, аудит-журнал, SLA-таймеры с Telegram-эскалацией, bulk-операции,
evidence-PDF (скриншоты, форензика, история цен, chain of custody) и текст жалобы под площадку.

**Надёжность.** Circuit breaker с автопереключением gemini↔grok, идемпотентность по `X-Request-ID`,
единый timeout budget, retry-queue на случай отказа всех провайдеров, token bucket,
JSON-логи + `/metrics` (Prometheus). Цели SLO и конфигурация — [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Мульти-тенантность.** Изоляция по `tenant_id` на уровне SQL, роли
`owner > admin > analyst > viewer` (+ `legal` — только кейсы и evidence), квоты тарифов
free/pro/business (402 при превышении), биллинг-вебхуки Stripe/ЮKassa с проверкой подписи,
партнёрский контур `/api/v1/partner/*` с per-key rate limit.

## Конфигурация

Основные переменные (полный список — `.env.example`):

| Переменная | Назначение |
|---|---|
| `GEMINI_API_KEY` / `GROK_API_KEY` | Ключи LLM-провайдеров |
| `API_SECRET_KEY` | Задан → требуется `X-API-Key`; не задан → open-mode (owner Default-тенанта) |
| `ALLOWED_ORIGINS` | CORS-источники (пусто = только same-origin) |
| `DB_PATH` | Путь к SQLite (в Docker — `/data/fakedetect.db`) |
| `LOG_FORMAT=json` | Структурные логи для продакшена |

## Документация

| Файл | Содержимое |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Архитектура, надёжность, пути масштабирования |
| [docs/architecture-decisions.md](docs/architecture-decisions.md) | Обоснование ключевых решений |
| [docs/COMPROMISES.md](docs/COMPROMISES.md) | Реестр упрощений и план их устранения |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | История изменений по блокам |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Деплой: VPS+Caddy, Render/Railway |
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | Краткая шпаргалка запуска |
| [frontend/README.md](frontend/README.md) | Архитектура SPA, команды, API-contract workflow |

## Разработка

```bash
pytest -v                          # backend-тесты
cd frontend && npm test            # frontend-тесты (Vitest + MSW)
cd frontend && npm run storybook   # дизайн-система на :6006
```

CI на каждый push/PR: backend (pytest + ruff) и frontend (lint, typecheck, тесты, build,
Storybook, drift-check OpenAPI-типов против живого бэкенда, Lighthouse, E2E Playwright).

## Roadmap

- [ ] Поддержка Авито и AliExpress
- [ ] Telegram-бот: отправил ссылку — получил результат
- [ ] Postgres + Row-Level Security (после стабилизации схемы тенантов)

## Лицензия

[MIT](LICENSE)


