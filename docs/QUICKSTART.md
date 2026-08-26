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
uvicorn app.main:app --reload   # или: uvicorn server:app --reload (legacy-алиас)
```

## 4. Открыть в браузере

http://localhost:8000

## Структура проекта

Актуальная структура репозитория — в [README.md](../README.md#архитектура).

### Новые компоненты

- **aggregator.py** — агрегирует результаты анализа из всех изображений
- **parsers/** — модульная система парсеров для разных маркетплейсов
- **/analyze-deep** — новый эндпоинт для глубокого анализа с авто-парсингом маркетплейса
- **/batch** — батч-обработка множества товаров

### Новые зависимости

- `beautifulsoup4>=4.12` — HTML парсер
- `lxml>=5.0` — быстрый XML/HTML парсер
