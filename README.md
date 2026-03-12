# FakeDetect — AI-детектор подделок

Система выявления контрафактных товаров на маркетплейсах (WB, Ozon, Яндекс Маркет). Использует Gemini 2.5 Flash Vision для визуального сравнения товаров.

## Структура проекта

```
Style_Check/
├── server.py              # FastAPI сервер
├── aggregator.py          # Агрегатор результатов анализа изображений
├── parsers/               # Пarsers для разных маркетплейсов
│   ├── base.py            # Базовый класс парсера
│   ├── wildberries.py     # Parser для Wildberries
│   ├── ozon.py            # Parser для Ozon
│   ├── yandex.py          # Parser для Яндекс Маркет
│   └── factory.py         # Фабрика парсеров
├── llm_provider.py        # Провайдеры LLM (Gemini, Grok)
├── index.html             # Frontend
├── requirements.txt       # Зависимости
└── .env                   # Конфигурация
```

## Установка

```bash
pip install -r requirements.txt
```

### Новые зависимости

- `beautifulsoup4>=4.12` — HTML парсер
- `lxml>=5.0` — XML/HTML парсер (быстрее)

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

## Запуск

```bash
uvicorn server:app --reload
```

Откройте в браузере: http://localhost:8000

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
- [ ] Docker + docker-compose для удобного запуска в одной команде
- [ ] Юнит-тесты для парсеров и LLM-провайдера

### v0.3 — Масштабирование
- [ ] Поддержка Авито и AliExpress
- [ ] Telegram-бот интерфейс: отправил ссылку — получил результат
