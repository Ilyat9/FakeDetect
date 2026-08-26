# Changelog

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
