-- ============================================================
-- Схема БД для модуля регистрации (uchet_db)
-- Выполнять под суперпользователем (postgres)
-- ============================================================

CREATE EXTENSION IF NOT EXISTS citext;

-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    id              BIGSERIAL PRIMARY KEY,
    email           CITEXT       UNIQUE NOT NULL,
    name            VARCHAR(100) NOT NULL,
    phone           VARCHAR(20)  NOT NULL,
    password_hash   VARCHAR(255),                       -- bcrypt hash, NULL пока пользователь не задал пароль
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    activated_at    TIMESTAMPTZ,
    last_login_at   TIMESTAMPTZ,
    CONSTRAINT users_status_check CHECK (status IN ('pending','active','disabled'))
);

-- Таблица одноразовых токенов для установки пароля
CREATE TABLE IF NOT EXISTS password_setup_tokens (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      CHAR(64)    NOT NULL UNIQUE,        -- SHA-256 hex (raw token хранится только у пользователя)
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    used_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tokens_user_id    ON password_setup_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_tokens_expires_at ON password_setup_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_users_status      ON users(status);

-- Таблица серверных сессий авторизации (Спринт 1.1).
-- Хранится только SHA-256 хеш Refresh-токена; сырой токен живёт лишь в куке клиента.
-- expires_at = ближайший из дедлайнов: «простой» (now + 1 час, сдвигается при обновлении)
-- и «абсолют» (session_started_at + 1 сутки, не сдвигается).
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash          CHAR(64)    NOT NULL UNIQUE,        -- SHA-256 hex
    expires_at          TIMESTAMPTZ NOT NULL,              -- скользящий дедлайн (idle / absolute)
    session_started_at  TIMESTAMPTZ NOT NULL DEFAULT now(), -- старт сессии (для абсолютного потолка)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Для уже развёрнутых БД (если таблица создавалась без session_started_at):
ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS session_started_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_refresh_user_id    ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_expires_at ON refresh_tokens(expires_at);

-- ============================================================
-- Роль приложения (вызывать отдельно, заменив пароль)
-- ============================================================
-- CREATE ROLE uchet_app WITH LOGIN PASSWORD 'CHANGE_ME_STRONG_PASSWORD';
-- GRANT CONNECT ON DATABASE uchet_db TO uchet_app;
-- GRANT USAGE  ON SCHEMA public TO uchet_app;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES   IN SCHEMA public TO uchet_app;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO uchet_app;
