# FakeDetect — AI-детектор подделок

Система выявления контрафактных товаров на маркетплейсах (WB, Ozon, Яндекс Маркет). Использует Gemini 2.5 Flash Vision для визуального сравнения товаров.

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

## 🗺️ Roadmap

### v0.2 — Фундамент
- [x] Docker + docker-compose для удобного запуска в одной команде
- [x] Юнит- и интеграционные тесты (pytest) + CI

### v0.3 — Масштабирование
- [ ] Поддержка Авито и AliExpress
- [ ] Telegram-бот интерфейс: отправил ссылку — получил результат
