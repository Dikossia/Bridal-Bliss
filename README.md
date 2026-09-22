# dress-rental — «Аренда свадебных платьев»

Django-версия проекта под сервер `82.115.49.183`, собранная по
`deploy-guide.md` (Docker + Postgres + Gunicorn + Nginx). Модуль
регистрации/входа портирован из исходного Node.js/Express-архива
(`auth-module.tar.gz`, проект «Учёт») на Django — с сохранением API,
контрактов и фронтенда без изменений.

## Откуда что взялось

| Было (архив «Учёт», Node.js) | Стало (этот репозиторий, Django) |
|---|---|
| `auth/server.js` (Express) | приложение `accounts/` (views.py, urls.py, models.py) |
| `auth/schema.sql` | `accounts/migrations/0001_initial.py` — те же 3 таблицы (`users`, `password_setup_tokens`, `refresh_tokens`) + `rate_limit_hits` |
| bcrypt (cost 12) в коде | `BCryptSHA256PasswordHasher` — встроенный хешер Django |
| express-rate-limit (in-memory) | свой rate-limit на БД (`RateLimitHit`) — **корректно работает при нескольких воркерах gunicorn**, в отличие от in-memory-счётчика одного Node-процесса |
| `auth/public/*.html` | скопированы как есть в `accounts/templates/accounts/*.html` — фронтенд не менялся |
| `shared/*` (тема, сайдбар, nav-config) | скопированы как есть в `assets/shared/` |
| JWT access (15 мин) + refresh-кука (idle 60 мин / абсолют 24ч) | тот же контракт, через `PyJWT` |

**Фронтенд не переписывался.** JS в HTML-страницах как и раньше ходит на
`/api/register`, `/api/login` и т.д. и ожидает тот же формат ответов —
поэтому страницы регистрации/входа/`home`/`dictionaries` работают без
правок. Разделы `/operations`, `/report`, `/admin/*`, `/dict/*` — это
пока только пункты меню в `shared/nav-config.js` (так было и в
оригинале): бэкенда под них нет ни там, ни здесь.

## Структура

```
dress-rental/
  manage.py
  requirements.txt
  .env.example
  Dockerfile
  docker-compose.yml
  nginx/default.conf
  config/            — настройки Django, urls, wsgi/asgi
  accounts/          — портированный auth-модуль
    models.py        — User, PasswordSetupToken, RefreshToken, RateLimitHit
    managers.py       — UserManager (create_user/create_superuser)
    views.py          — страницы + /api/*
    utils.py          — токены, письма, JWT, rate-limit
    admin.py          — Django-админка для User/токенов
    migrations/0001_initial.py
    templates/accounts/*.html  — фронтенд из архива, без изменений
  assets/            — styles.css + shared/ (тема, сайдбар, nav) из архива
```

## ⚠️ Важно: миграцию нужно перепроверить локально

Я собирал этот проект в среде без доступа к PyPI, поэтому **не смог
установить сам Django и прогнать `manage.py check` / `migrate`**.
Код вычитан вручную и синтаксически проверен (`py_compile`), но
`accounts/migrations/0001_initial.py` написан руками, а не сгенерирован
командой `makemigrations` — по конструкции она должна быть верной, но
**перед первым деплоем обязательно проверьте**:

```bash
pip install -r requirements.txt
python manage.py makemigrations --check --dry-run
```

Если Django скажет, что миграций не хватает — просто примите
предложенные изменения (`python manage.py makemigrations`) и закоммитьте
результат. Остальной код (views/models/utils) от использования Django
не зависит настолько критично и логика в нём проверена вручную построчно
по оригинальному `server.js`.

## Локальный запуск (без Docker, для разработки)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# впишите в .env хотя бы SECRET_KEY, JWT_SECRET и данные локального Postgres
# (или временно поставьте DB_HOST=localhost и поднимите Postgres в Docker)
python manage.py makemigrations --check --dry-run   # см. предупреждение выше
python manage.py migrate
python manage.py createsuperuser                     # спросит email, name, phone, password
python manage.py runserver
```

Откройте http://127.0.0.1:8000/register

## Деплой на сервер

Полная пошаговая инструкция — в `deploy-guide.md` (шаги 1–10: подключение,
firewall, Docker, перенос проекта, `.env`, `docker compose up -d --build`,
миграции/суперпользователь, HTTPS через certbot, бэкапы). Имена сервисов
в `docker-compose.yml` (`dress-postgres`, `dress-backend`, `dress-nginx`)
и переменные в `.env.example` (`DB_*`, `SECRET_KEY`, `ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS`) уже совпадают с тем, что описано в гайде — можно
следовать ему буквально.

Дополнительно (в `.env`, гайд про них не знал, т.к. писался под другой
модуль) заполните: `JWT_SECRET`, `APP_BASE_URL`, `SMTP_HOST/PORT/USER/PASSWORD/FROM`
— без SMTP не уйдут письма для завершения регистрации и сброса пароля.

## API (контракт не изменился)

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/register` | `{email, name, phone}` — регистрация, письмо со ссылкой на `/set-password` |
| GET  | `/api/verify-token?token=` | проверка токена (регистрация/сброс) |
| POST | `/api/set-password` | `{token, password}` — завершение регистрации |
| POST | `/api/forgot-password` | `{email}` — запрос письма для сброса пароля |
| POST | `/api/reset-password` | `{token, password}` — сброс пароля, разлогинивает все сессии |
| POST | `/api/login` | `{email, password}` → `{accessToken, user}` + `refreshToken` в httpOnly-куке |
| POST | `/api/refresh` | обновление пары токенов по куке |
| POST | `/api/logout` | завершение сессии |

## Известные упрощения / что стоит сделать дальше

- **CSRF**: API-эндпоинты помечены `@csrf_exempt` — как и в оригинале, где
  CSRF-защиты не было вовсе (полагались на `SameSite=Lax` для куки
  refresh-токена). Это не хуже оригинала, но и не лучше — если появится
  время, стоит перейти на настоящий CSRF-токен Django для POST-запросов.
- Rate limiting и «мастер-данные» (`/dict/*`, `/operations`, `/report`,
  `/admin/*`) — не реализованы, как и в исходном архиве.
- `django.views.static.serve`-подобная раздача `/styles.css` и `/shared/*`
  через Django — рабочий вариант для этого масштаба, но при росте нагрузки
  логичнее отдавать их прямо из Nginx (volume с `assets/`), не трогая
  Gunicorn.
