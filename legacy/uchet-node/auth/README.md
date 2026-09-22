# Uchet — модуль регистрации

Веб-модуль регистрации пользователей с подтверждением email через magic-link и установкой пароля.

## Состав

```
uchet/
├── schema.sql            # SQL для создания таблиц в uchet_db
├── package.json          # Зависимости Node.js
├── .env.example          # Шаблон переменных окружения
├── server.js             # Backend (Express + pg + nodemailer + bcrypt)
└── public/
    ├── styles.css        # Общие стили
    ├── register.html     # Страница регистрации
    ├── set-password.html # Страница установки пароля
    └── login.html        # Страница входа (заглушка)
```

## Быстрый запуск (локально для тестов)

```bash
# 1. Установить зависимости
npm install

# 2. Скопировать конфиг и заполнить
cp .env.example .env
nano .env

# 3. Применить схему БД (один раз)
psql -h 213.155.23.230 -U postgres -d uchet_db -f schema.sql

# 4. Запустить
npm start
```

Откройте http://localhost:3000/register

## Деплой на сервер (213.155.23.230)

См. раздел «Пошаговая инструкция» в чате — там полная инструкция с Nginx, certbot и systemd.

Краткая шпаргалка по systemd:

```bash
sudo cp -r uchet /opt/uchet
cd /opt/uchet && npm install --production
sudo chown -R www-data:www-data /opt/uchet

# /etc/systemd/system/uchet.service — содержимое из инструкции
sudo systemctl daemon-reload
sudo systemctl enable --now uchet
sudo systemctl status uchet
```

## API

| Метод | Путь | Описание |
|---|---|---|
| POST | `/api/register` | Регистрация: `{email, name, phone}` |
| GET  | `/api/verify-token?token=...` | Проверка валидности токена |
| POST | `/api/set-password` | Установка пароля: `{token, password}` |

## Безопасность

- Пароли — bcrypt (cost 12)
- Токены — 32 байта случайных данных, хранится только SHA-256 хеш
- TTL токена — 24 часа, одноразовый
- Rate limit на регистрацию — 5 запросов / 15 мин с IP
- Anti-enumeration: всегда отвечаем `ok:true` на регистрацию
- Helmet для security-headers
- Параметризованные SQL-запросы (защита от SQL-injection)

## Что НЕ входит (на следующий спринт)

- Реальный логин и сессии
- «Забыли пароль» (механизм такой же, как при регистрации)
- 2FA
- Аудит-лог
