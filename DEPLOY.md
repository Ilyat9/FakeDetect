# Деплой публичного демо (портфолио)

Гайд для сценария «человек зашёл по ссылке и потестил». Демо-режим (`DEMO_MODE=true`)
даёт анонимным посетителям права analyst Default-тенанта с защитой бюджета:

- per-IP лимиты: 6 анализов/мин и 40 запросов/мин на посетителя;
- жёсткий кап демо-тенанта: 200 проверок/месяц (`DEMO_MAX_CHECKS_PER_MONTH`);
- `/metrics` скрыт от анонимов (`METRICS_PUBLIC=false`).

## Вариант A — дешёвый VPS + Docker Compose + Caddy (рекомендуется)

Полный контроль, доступ к WB/Ozon из РФ, постоянный диск (история и evidence живут
между рестартами). Стоимость: ~300–500 ₽/мес за VPS 1 vCPU / 2 GB.

```bash
# На сервере:
git clone <repo> && cd FakeDetect
cp .env.example .env
# Минимальный .env для демо:
#   GEMINI_API_KEY=AIza...          # бесплатный тариф aistudio.google.com
#   DEMO_MODE=true
#   LOG_FORMAT=json                 # опционально
docker compose up -d --build
```

HTTPS через Caddy (авто-cert):

```
# /etc/caddy/Caddyfile
demo.yourdomain.ru {
    reverse_proxy 127.0.0.1:8000
}
```

Обновление: `git pull && docker compose up -d --build`.

## Вариант B — Render / Railway / Fly.io (быстрее старт)

Плюсы: деплой из GitHub в два клика, TLS из коробки.
Минусы: free-tier контейнеры засыпают (первый запрос ~30 сек) и **эфемерный диск** —
SQLite и evidence/ пропадут при редеплое (для демо приемлемо; подключите их
persistent disk при желании).

Настройки: Docker-деплой из репозитория, порт 8000, env те же
(`GEMINI_API_KEY`, `DEMO_MODE=true`).

## Чеклист безопасности публичного демо

- [x] `DEMO_MODE=true` → анонимы = analyst + per-IP лимиты
- [x] Кап демо-тенанта 200 проверок/мес (бюджет Gemini защищён)
- [x] `/metrics` закрыт (`METRICS_PUBLIC=false`)
- [ ] `API_SECRET_KEY` оставить пустым ИЛИ задать и добавить ключ в UI —
      не оставляйте прод-секреты в .env демо-машины
- [ ] Telegram-токены на демо не указывать (алерты пойдут в ваш чат)
- [x] Биллинг-вебхуки fail-closed без секретов
- [ ] Бэкап `fakedetect.db` (cron: sqlite3 .backup) — опционально

## Стоимость

Gemini free tier: лимит RPM/RPD покрывает демо-трафик портфолио. Жёсткие предохранители
внутри приложения: месячный кап тенанта + per-IP троттлинг + circuit breaker.
Ожидаемый денежный расход при бесплатном тарифе Gemini: **0 ₽**.
