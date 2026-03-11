# Быстрый старт

## 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

## 2. Настройка

Создайте файл `.env`:

```bash
cp .env.example .env
```

Добавьте API ключ:

```bash
echo "GEMINI_API_KEY=ваш_ключ" > .env
```

Ключ для Gemini бесплатный: https://aistudio.google.com

## 3. Запуск

```bash
uvicorn server:app --reload
```

## 4. Открыть в браузере

http://localhost:8000

## Структура проекта

```
Style_Check/
├── server.py              # FastAPI сервер
├── aggregator.py          # Агрегатор результатов анализа
├── parsers/               # Пarsers маркетплейсов
│   ├── base.py            # Базовый класс
│   ├── wildberries.py     # WB
│   ├── ozon.py            # Ozon
│   ├── yandex.py          # Яндекс
│   └── factory.py         # Фабрика
├── llm_provider.py        # LLM провайдеры
├── index.html             # Frontend
├── .env.example           # Конфиг
├── requirements.txt       # Зависимости
└── README.md              # Документация
```

### Новые компоненты

- **aggregator.py** — агрегирует результаты анализа из всех изображений
- **parsers/** — модульная система парсеров для разных маркетплейсов
- **/analyze-deep** — новый эндпоинт для глубокого анализа с авто-парсингом маркетплейса
- **/batch** — батч-обработка множества товаров

### Новые зависимости

- `beautifulsoup4>=4.12` — HTML парсер
- `lxml>=5.0` — быстрый XML/HTML парсер
