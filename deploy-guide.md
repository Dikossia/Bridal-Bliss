# Развёртывание приложения «Аренда свадебных платьев» на сервере

Пошаговая инструкция: от пустого Linux-сервера до работающего сайта с HTTPS.
Стек: Python 3.13 · Django 5.2 LTS · PostgreSQL 16 · Gunicorn · Nginx · Docker.

> Исходная точка: **пустой сервер, только что установленная Ubuntu, больше
> ничего нет.** Всё, что нужно, ставим и настраиваем по шагам ниже —
> на сам сервер добавляется только Docker, остальное живёт в контейнерах.
> Сервер: `82.115.49.183`. Пользователь для входа: `ubuntu` (замените, если
> у вас другой — например `root`).

---

## Что понадобится заранее

- Доступ к серверу по SSH (пользователь с `sudo`, например `ubuntu`).
- Архив проекта `dress-rental.zip` (собранный ранее скелет).
- Домен (опционально, но нужен для HTTPS). Например `platya.kz`.

---

## Шаг 1. Подключиться к серверу и обновить систему

```bash
ssh ubuntu@82.115.49.183

sudo apt update && sudo apt upgrade -y
```

Если перезагрузка потребуется (ядро обновилось) — `sudo reboot`, затем зайдите снова.

---

## Шаг 2. Настроить фаервол

Открываем только SSH, HTTP и HTTPS. Остальное закрыто.

```bash
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status        # проверить, что правила на месте
```

> Порт Postgres (5432) наружу НЕ открываем — база доступна только контейнерам
> по внутренней сети Docker. Это уже заложено в `docker-compose.yml`.

---

## Шаг 3. Установить Docker

Официальный скрипт установки Docker + Compose:

```bash
curl -fsSL https://get.docker.com | sudo sh
```

Разрешаем запускать docker без `sudo` (чтобы не писать sudo каждый раз):

```bash
sudo usermod -aG docker $USER
```

**Важно:** выйдите из SSH и зайдите заново — иначе группа не применится.

```bash
exit
ssh ubuntu@82.115.49.183
docker --version           # должно показать версию
docker compose version     # и здесь тоже
```

---

## Шаг 4. Перенести проект на сервер

Два способа — выберите один.

> В командах ниже используется домашняя папка `/home/ubuntu`. Если вы заходите
> на сервер под `root`, замените её на `/root` (или на путь своего пользователя)
> во всех командах, где она встречается — здесь, в бэкапах и в cron.

**Вариант А — через scp (проще всего).** С вашего компьютера:

```bash
scp dress-rental.zip ubuntu@82.115.49.183:/home/ubuntu/
```

Затем на сервере:

```bash
sudo apt install -y unzip
cd /home/ubuntu
unzip dress-rental.zip
cd dress-rental
```

**Вариант Б — через Git** (если завели репозиторий):

```bash
cd /home/ubuntu
git clone <ваш-репозиторий> dress-rental
cd dress-rental
```

---

## Шаг 5. Настроить секреты в `.env`

Копируем шаблон и заполняем реальными значениями:

```bash
cp .env.example .env
```

Сгенерируйте надёжный `SECRET_KEY` одной командой:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

Откройте `.env` и впишите значения:

```bash
nano .env
```

```ini
SECRET_KEY=<вставьте_сгенерированный_ключ>
DEBUG=False
ALLOWED_HOSTS=platya.kz,www.platya.kz,82.115.49.183
CSRF_TRUSTED_ORIGINS=https://platya.kz

DB_NAME=dress_db
DB_USER=dress_app
DB_PASSWORD=<придумайте_надёжный_пароль>
DB_HOST=postgres
DB_PORT=5432
```

Сохранить в nano: `Ctrl+O`, `Enter`, затем `Ctrl+X`.

> `.env` содержит секреты и уже в `.gitignore` — НИКОГДА не коммитьте его
> и не кладите в общий проект Claude. Туда — только `.env.example`.

---

## Шаг 6. Собрать и запустить контейнеры

```bash
docker compose up -d --build
```

Первый запуск займёт несколько минут (скачивание образов + сборка).
Проверить, что все три контейнера поднялись:

```bash
docker compose ps
```

Должны быть `dress-postgres`, `dress-backend`, `dress-nginx` — все в статусе `Up`.

Если что-то упало — смотрим логи конкретного сервиса:

```bash
docker compose logs backend
docker compose logs nginx
```

---

## Шаг 7. Применить миграции и создать администратора

База поднялась пустой — накатываем схему и заводим вход в админку:

```bash
docker compose exec backend python manage.py migrate

docker compose exec backend python manage.py createsuperuser
```

Система спросит логин, email и пароль администратора — это учётка для входа
в панель сотрудников.

---

## Шаг 8. Проверить, что всё работает

Откройте в браузере:

- Сайт-каталог: `http://82.115.49.183/`
- Панель сотрудников: `http://82.115.49.183/admin/`

Зайдите в админку под созданной учёткой, добавьте первое платье (с фото) —
оно должно сразу появиться в каталоге на главной.

**На этом рабочая версия по HTTP готова.** Дальше — домен и HTTPS
(обязательно перед приёмом оплаты).

---

## Шаг 9. Домен и HTTPS (Let's Encrypt)

### 9.1. Направить домен на сервер

У регистратора домена создайте A-записи:

| Тип | Имя | Значение |
|-----|-----|----------|
| A | @ | 82.115.49.183 |
| A | www | 82.115.49.183 |

Подождите, пока записи разойдутся (обычно от минут до пары часов). Проверить:

```bash
ping platya.kz     # должен отвечать ваш IP
```

### 9.2. Обновить конфиг Nginx для получения сертификата

Замените содержимое `nginx/default.conf` на версию, которая умеет отдавать
проверку Let's Encrypt (ACME) и переадресовывать на HTTPS. Пока без 443-блока:

```bash
nano nginx/default.conf
```

```nginx
server {
    listen 80;
    server_name platya.kz www.platya.kz;

    # Проверочный путь для Let's Encrypt
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Всё остальное временно проксируем как есть
    location / {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 9.3. Добавить сервис certbot в docker-compose

Откройте `docker-compose.yml` и добавьте сервис `certbot` и два тома.
В сервис `nginx` добавьте монтирование этих же томов:

```yaml
  nginx:
    # ... существующие строки ...
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
      - media_data:/media:ro
      - certbot_certs:/etc/letsencrypt:ro       # добавить
      - certbot_www:/var/www/certbot            # добавить

  certbot:
    image: certbot/certbot
    container_name: dress-certbot
    volumes:
      - certbot_certs:/etc/letsencrypt
      - certbot_www:/var/www/certbot
    networks:
      - dress-net
```

И в раздел `volumes:` внизу файла:

```yaml
volumes:
  postgres_data:
  media_data:
  certbot_certs:     # добавить
  certbot_www:       # добавить
```

Перезапустить nginx с новым конфигом и томами:

```bash
docker compose up -d
```

### 9.4. Получить сертификат

Замените email на свой:

```bash
docker compose run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  -d platya.kz -d www.platya.kz \
  --email you@example.com --agree-tos --no-eff-email
```

При успехе certbot скажет `Congratulations!` и покажет путь к сертификату.

### 9.5. Включить HTTPS в Nginx

Снова откройте `nginx/default.conf` и приведите к финальному виду —
80-й порт редиректит на 443, весь трафик идёт по HTTPS:

```nginx
# HTTP -> редирект на HTTPS (+ путь для обновления сертификата)
server {
    listen 80;
    server_name platya.kz www.platya.kz;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS
server {
    listen 443 ssl;
    server_name platya.kz www.platya.kz;

    ssl_certificate     /etc/letsencrypt/live/platya.kz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/platya.kz/privkey.pem;

    client_max_body_size 20M;

    location /media/ {
        alias /media/;
        access_log off;
        expires 30d;
    }

    location / {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Также в `docker-compose.yml` у сервиса `nginx` откройте 443-й порт:

```yaml
    ports:
      - "80:80"
      - "443:443"     # добавить
```

Перезапустить:

```bash
docker compose up -d
```

Теперь сайт открывается по `https://platya.kz` с замком в адресной строке.

### 9.6. Автопродление сертификата

Сертификат Let's Encrypt живёт 90 дней. Добавьте задачу в cron, чтобы
он продлевался сам:

```bash
crontab -e
```

Добавьте строку (продление раз в неделю + перезагрузка nginx):

```cron
0 3 * * 1 cd /home/ubuntu/dress-rental && docker compose run --rm certbot renew && docker compose exec nginx nginx -s reload
```

---

## Шаг 10. Резервные копии базы данных

Данные о платьях, клиентах и бронированиях — самое ценное. Настройте бэкапы.

**Ручной бэкап (проверить, что работает):**

```bash
docker compose exec -T postgres pg_dump -U dress_app dress_db > backup_$(date +%F).sql
```

**Автоматический бэкап раз в сутки через cron:**

```bash
mkdir -p /home/ubuntu/backups
crontab -e
```

```cron
0 2 * * * cd /home/ubuntu/dress-rental && docker compose exec -T postgres pg_dump -U dress_app dress_db > /home/ubuntu/backups/dress_$(date +\%F).sql
```

> Раз в неделю копируйте папку `backups/` куда-то ВНЕ сервера
> (свой компьютер, облако). Бэкап на том же сервере не спасёт при его потере.

**Восстановление из бэкапа (если понадобится):**

```bash
cat backup_2026-09-19.sql | docker compose exec -T postgres psql -U dress_app -d dress_db
```

---

## Повседневные операции (шпаргалка)

| Задача | Команда |
|--------|---------|
| Посмотреть статус | `docker compose ps` |
| Логи бэкенда | `docker compose logs -f backend` |
| Перезапустить всё | `docker compose restart` |
| Остановить всё | `docker compose down` |
| Поднять всё | `docker compose up -d` |
| Обновить код после `git pull` | `docker compose up -d --build` |
| Применить новые миграции | `docker compose exec backend python manage.py migrate` |
| Зайти в shell бэкенда | `docker compose exec backend bash` |

---

## Обновление приложения (важный ритуал)

Когда меняете модели (добавили поле платью, новый статус) — после переноса
кода на сервер ОБЯЗАТЕЛЬНО:

```bash
# 1. забрать новый код
git pull            # или заново scp + unzip

# 2. пересобрать и поднять
docker compose up -d --build

# 3. создать и применить миграции
docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py migrate
```

Если пропустить `makemigrations`/`migrate` — получите ошибку рассинхрона
схемы БД. Это самый частый «магический» баг Django. Держите этот порядок.

---

## Если что-то пошло не так

- **Сайт не открывается** → `docker compose ps` (все ли `Up`?),
  затем `docker compose logs nginx` и `docker compose logs backend`.
- **502 Bad Gateway** → упал backend. Смотрите `docker compose logs backend`,
  чаще всего ошибка в `.env` или не применены миграции.
- **Ошибка про ALLOWED_HOSTS** → добавьте домен/IP в `ALLOWED_HOSTS` в `.env`
  и `docker compose up -d`.
- **Не грузятся стили админки** → пересоберите:
  `docker compose up -d --build` (collectstatic выполняется при сборке).
- **certbot не выдал сертификат** → проверьте, что домен реально указывает
  на сервер (`ping platya.kz`) и порт 80 открыт в ufw.
