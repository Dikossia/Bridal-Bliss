// ============================================================
// Uchet — Registration, Password Setup & Auth backend
// ============================================================
require('dotenv').config();

const path         = require('path');
const crypto       = require('crypto');
const express      = require('express');
const helmet       = require('helmet');
const bcrypt       = require('bcrypt');
const rateLimit    = require('express-rate-limit');
const nodemailer   = require('nodemailer');
const jwt          = require('jsonwebtoken');
const cookieParser = require('cookie-parser');
const { Pool }     = require('pg');

// ------------------- Конфиг -------------------
const PORT           = parseInt(process.env.PORT || '3000', 10);
const APP_BASE_URL   = process.env.APP_BASE_URL || `http://localhost:${PORT}`;
const TOKEN_TTL_HRS  = parseInt(process.env.TOKEN_TTL_HOURS || '24', 10);
const RESET_TOKEN_TTL_HRS = parseInt(process.env.RESET_TOKEN_TTL_HOURS || '1', 10); // TTL для сброса пароля (1 час)
const BCRYPT_COST    = parseInt(process.env.BCRYPT_COST || '12', 10);
const JWT_SECRET     = process.env.JWT_SECRET || 'fallback_default_secret_change_me';

// Сроки жизни сессии (refresh-токен)
const REFRESH_TTL_HOURS = parseInt(process.env.REFRESH_TTL_HOURS   || '24', 10); // абсолютный потолок (1 сутки)
const IDLE_TIMEOUT_MIN  = parseInt(process.env.IDLE_TIMEOUT_MINUTES || '60', 10); // таймаут бездействия (1 час)
const MAX_SESSION_MS    = REFRESH_TTL_HOURS * 3600 * 1000;
const IDLE_TIMEOUT_MS   = IDLE_TIMEOUT_MIN * 60 * 1000;

// ------------------- БД -------------------
const pool = new Pool({
  host:     process.env.PGHOST,
  port:     parseInt(process.env.PGPORT || '5432', 10),
  database: process.env.PGDATABASE,
  user:     process.env.PGUSER,
  password: process.env.PGPASSWORD,
  max: 10,
});

// ------------------- SMTP -------------------
const mailer = nodemailer.createTransport({
  host:   process.env.SMTP_HOST,
  port:   parseInt(process.env.SMTP_PORT || '587', 10),
  secure: process.env.SMTP_SECURE === 'true',
  auth: {
    user: process.env.SMTP_USER,
    pass: process.env.SMTP_PASSWORD,
  },
});

// ------------------- Утилиты -------------------
const EMAIL_RE = /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$/;
const PHONE_RE = /^\+?[0-9\s\-()]{10,20}$/;

function isStrongPassword(pwd) {
  if (typeof pwd !== 'string' || pwd.length < 10) return false;
  if (!/[A-Za-z]/.test(pwd)) return false;
  if (!/[0-9]/.test(pwd))    return false;
  if (!/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(pwd)) return false;
  return true;
}

function sha256hex(s) {
  return crypto.createHash('sha256').update(s).digest('hex');
}

async function sendSetupEmail(to, name, rawToken) {
  const url = `${APP_BASE_URL}/set-password?token=${rawToken}`;
  const html = `
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:auto;color:#222">
      <h2 style="color:#2855af">Здравствуйте, ${escapeHtml(name)}!</h2>
      <p>Спасибо за регистрацию в системе «Учёт». Чтобы завершить регистрацию, установите пароль:</p>
      <p style="text-align:center;margin:32px 0">
        <a href="${url}"
           style="background:#2855af;color:#fff;text-decoration:none;
                  padding:12px 24px;border-radius:6px;display:inline-block;font-weight:600">
          Установить пароль
        </a>
      </p>
      <p style="font-size:13px;color:#666">If button doesn't work, copy link to browser:<br>
        <a href="${url}">${url}</a>
      </p>
      <p style="font-size:13px;color:#666">Ссылка действительна ${TOKEN_TTL_HRS} часа. Если вы не регистрировались — просто проигнорируйте это письмо.</p>
    </div>`;
  await mailer.sendMail({
    from:    process.env.SMTP_FROM,
    to,
    subject: 'Завершите регистрацию в системе Учёт',
    html,
  });
}

async function sendResetEmail(to, name, rawToken) {
  const url = `${APP_BASE_URL}/reset-password?token=${rawToken}`;
  const html = `
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:auto;color:#222">
      <h2 style="color:#2855af">Восстановление пароля</h2>
      <p>Здравствуйте, ${escapeHtml(name)}!</p>
      <p>Был получен запрос на восстановление пароля для вашего аккаунта в системе «Учёт».</p>
      <p>Чтобы задать новый пароль, нажмите кнопку ниже:</p>
      <p style="text-align:center;margin:32px 0">
        <a href="${url}"
           style="background:#2855af;color:#fff;text-decoration:none;
                  padding:12px 24px;border-radius:6px;display:inline-block;font-weight:600">
          Сбросить пароль
        </a>
      </p>
      <p style="font-size:13px;color:#666">Если кнопка не работает, скопируйте ссылку в браузер:<br>
        <a href="${url}">${url}</a>
      </p>
      <p style="font-size:13px;color:#666">Ссылка действительна ${RESET_TOKEN_TTL_HRS} час. Если вы не запрашивали сброс пароля — просто проигнорируйте это письмо.</p>
    </div>`;
  await mailer.sendMail({
    from:    process.env.SMTP_FROM,
    to,
    subject: 'Сброс пароля в системе Учёт',
    html,
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

// Конфигурация куки для Refresh токена
const USE_SECURE_COOKIE = String(process.env.APP_BASE_URL || '').startsWith('https://');
const REFRESH_COOKIE_OPTIONS = {
  httpOnly: true,
  secure: USE_SECURE_COOKIE,
  sameSite: 'lax',
  path: '/api/refresh',
};

function computeRefreshExpiry(sessionStartedAtMs) {
  const idleDeadline     = Date.now() + IDLE_TIMEOUT_MS;
  const absoluteDeadline = sessionStartedAtMs + MAX_SESSION_MS;
  return new Date(Math.min(idleDeadline, absoluteDeadline));
}

function cookieWithExpiry(expiresAt) {
  return { ...REFRESH_COOKIE_OPTIONS, maxAge: Math.max(0, expiresAt.getTime() - Date.now()) };
}

// ------------------- App -------------------
const app = express();
app.set("trust proxy", 1);
app.use(helmet({ contentSecurityPolicy: false }));
app.use(express.json({ limit: '16kb' }));
app.use(cookieParser());
app.use(express.static(path.join(__dirname, 'public')));
app.use('/shared', express.static(path.join(__dirname, 'shared')));

// Лимиты на запросы
const registerLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 5,
  standardHeaders: true,
  legacyHeaders: false,
  message: { ok: false, error: 'Слишком много запросов. Попробуйте позже.' },
});

const loginLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 10,
  standardHeaders: true,
  legacyHeaders: false,
  message: { ok: false, error: 'Слишком много попыток входа. Попробуйте позже.' },
});

// Middleware для проверки JWT Access токена
function authenticateToken(req, res, next) {
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1];

  if (!token) return res.status(401).json({ ok: false, error: 'Токен отсутствует' });

  jwt.verify(token, JWT_SECRET, (err, user) => {
    if (err) return res.status(403).json({ ok: false, error: 'Токен недействителен или истёк' });
    req.user = user;
    next();
  });
}

// ------------------- Маршруты страниц -------------------
app.get('/',             (_, res) => res.redirect('/register'));
app.get('/register',      (_, res) => res.sendFile(path.join(__dirname, 'public', 'register.html')));
app.get('/login',         (_, res) => res.sendFile(path.join(__dirname, 'public', 'login.html')));
app.get('/home',          (_, res) => res.sendFile(path.join(__dirname, 'public', 'home.html')));
app.get('/dictionaries', (_, res) => res.sendFile(path.join(__dirname, 'public', 'dictionaries.html')));
app.get('/set-password',  (_, res) => res.sendFile(path.join(__dirname, 'public', 'set-password.html')));
app.get('/forgot-password', (_, res) => res.sendFile(path.join(__dirname, 'public', 'forgot-password.html')));
app.get('/reset-password',  (_, res) => res.sendFile(path.join(__dirname, 'public', 'reset-password.html')));

// Пример защищённого роута для проверки
app.get('/dashboard',     (_, res) => res.send('Добро пожаловать в личный кабинет «Учёт»!'));

// ------------------- API: Регистрация -------------------
app.post('/api/register', registerLimiter, async (req, res) => {
  try {
    const email = String(req.body.email || '').trim().toLowerCase();
    const name  = String(req.body.name  || '').trim();
    const phone = String(req.body.phone || '').trim();

    if (!EMAIL_RE.test(email))      return res.status(400).json({ ok:false, error:'Некорректный email' });
    if (name.length < 2 || name.length > 100) return res.status(400).json({ ok:false, error:'Имя должно содержать от 2 до 100 символов' });
    if (!PHONE_RE.test(phone))      return res.status(400).json({ ok:false, error:'Некорректный телефон' });

    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      const found = await client.query('SELECT id, status FROM users WHERE email = $1', [email]);
      let userId;

      if (found.rowCount === 0) {
        const ins = await client.query(
          'INSERT INTO users (email, name, phone) VALUES ($1, $2, $3) RETURNING id',
          [email, name, phone]
        );
        userId = ins.rows[0].id;
      } else {
        userId = found.rows[0].id;
        
        // Защита от перебора: Если пользователь уже активен, имитируем успех и шлем напоминание
        if (found.rows[0].status === 'active') {
          await client.query('COMMIT');
          client.release();

          try {
            await mailer.sendMail({
              from: process.env.SMTP_FROM,
              to: email,
              subject: 'Попытка повторной регистрации в системе Учёт',
              html: `
                <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#222">
                  <h2 style="color:#2855af">Здравствуйте, ${escapeHtml(name)}!</h2>
                  <p>Кто-то (возможно, вы) попытался зарегистрировать аккаунт на этот email в системе «Учёт».</p>
                  <p>Ваша учётная запись уже создана и активна. Если вы забыли свой пароль, вы можете восстановить его по ссылке ниже:</p>
                  <p style="text-align:center;margin:32px 0">
                    <a href="${APP_BASE_URL}/forgot-password" style="background:#2855af;color:#fff;text-decoration:none;padding:12px 24px;border-radius:6px;display:inline-block;font-weight:600">
                      Восстановить пароль
                    </a>
                  </p>
                  <p style="font-size:13px;color:#666">Если это были не вы, просто проигнорируйте это письмо.</p>
                </div>`
            });
          } catch (mailErr) {
            console.error('[register] active user notification failed:', mailErr.message);
          }

          return res.json({ ok: true });
        }
        
        // Если пользователь не завершил регистрацию (pending) — обновляем данные и перевыпускаем токен
        await client.query('UPDATE users SET name = $1, phone = $2 WHERE id = $3', [name, phone, userId]);
        await client.query('DELETE FROM password_setup_tokens WHERE user_id = $1 AND used_at IS NULL', [userId]);
      }

      const rawToken  = crypto.randomBytes(32).toString('hex');
      const tokenHash = sha256hex(rawToken);
      const expiresAt = new Date(Date.now() + TOKEN_TTL_HRS * 3600 * 1000);

      await client.query(
        'INSERT INTO password_setup_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3)',
        [userId, tokenHash, expiresAt]
      );
      await client.query('COMMIT');

      try {
        await sendSetupEmail(email, name, rawToken);
      } catch (mailErr) {
        console.error('[register] mail send failed:', mailErr.message);
      }

      return res.json({ ok:true });
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
  } catch (err) {
    console.error('[register] error:', err);
    return res.status(500).json({ ok:false, error:'Внутренняя ошибка сервера' });
  }
});

// ------------------- API: Проверка токена регистрации и сброса -------------------
app.get('/api/verify-token', async (req, res) => {
  const raw = String(req.query.token || '');
  if (!/^[a-f0-9]{64}$/.test(raw)) return res.json({ ok:false });
  const h = sha256hex(raw);
  const r = await pool.query(
    `SELECT 1 FROM password_setup_tokens
      WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()`,
    [h]
  );
  return res.json({ ok: r.rowCount > 0 });
});

// ------------------- API: Установка пароля -------------------
app.post('/api/set-password', async (req, res) => {
  try {
    const raw      = String(req.body.token    || '');
    const password = String(req.body.password || '');

    if (!/^[a-f0-9]{64}$/.test(raw))   return res.status(400).json({ ok:false, error:'Некорректный токен' });
    if (!isStrongPassword(password))   return res.status(400).json({ ok:false, error:'Пароль не соответствует требованиям' });

    const tokenHash = sha256hex(raw);
    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      const tk = await client.query(
        `SELECT id, user_id FROM password_setup_tokens
          WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()
          FOR UPDATE`,
        [tokenHash]
      );
      if (tk.rowCount === 0) {
        await client.query('ROLLBACK');
        return res.status(400).json({ ok:false, error:'Ссылка недействительна или истекла' });
      }
      const userId  = tk.rows[0].user_id;
      const tokenId = tk.rows[0].id;
      const hash = await bcrypt.hash(password, BCRYPT_COST);
      await client.query(
        `UPDATE users SET password_hash = $1, status = 'active', activated_at = now() WHERE id = $2`,
        [hash, userId]
      );
      await client.query(`UPDATE password_setup_tokens SET used_at = now() WHERE id = $1`, [tokenId]);
      await client.query(
        `DELETE FROM password_setup_tokens WHERE user_id = $1 AND used_at IS NULL`,
        [userId]
      );
      await client.query('COMMIT');
      return res.json({ ok:true });
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
  } catch (err) {
    console.error('[set-password] error:', err);
    return res.status(500).json({ ok:false, error:'Внутренняя ошибка сервера' });
  }
});

// ------------------- API: Запрос сброса пароля -------------------
app.post('/api/forgot-password', registerLimiter, async (req, res) => {
  try {
    const email = String(req.body.email || '').trim().toLowerCase();
    if (!EMAIL_RE.test(email)) return res.status(400).json({ ok: false, error: 'Некорректный email' });

    const client = await pool.connect();
    try {
      // Ищем только активного пользователя
      const found = await client.query('SELECT id, name, status FROM users WHERE email = $1', [email]);
      
      // Anti-enumeration: если пользователя нет или он неактивен, имитируем успех
      if (found.rowCount === 0 || found.rows[0].status !== 'active') {
        return res.json({ ok: true });
      }

      const userId = found.rows[0].id;
      const name   = found.rows[0].name;

      await client.query('BEGIN');
      
      // Чистим старые неиспользованные токены сброса/установки
      await client.query('DELETE FROM password_setup_tokens WHERE user_id = $1 AND used_at IS NULL', [userId]);

      // Создаем токен с коротким TTL (1 час)
      const rawToken  = crypto.randomBytes(32).toString('hex');
      const tokenHash = sha256hex(rawToken);
      const expiresAt = new Date(Date.now() + RESET_TOKEN_TTL_HRS * 3600 * 1000);

      await client.query(
        'INSERT INTO password_setup_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3)',
        [userId, tokenHash, expiresAt]
      );
      await client.query('COMMIT');

      try {
        await sendResetEmail(email, name, rawToken);
      } catch (mailErr) {
        console.error('[forgot-password] mail send failed:', mailErr.message);
      }

      return res.json({ ok: true });
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
  } catch (err) {
    console.error('[forgot-password] error:', err);
    return res.status(500).json({ ok: false, error: 'Внутренняя ошибка сервера' });
  }
});

// ------------------- API: Сброс пароля по токену -------------------
app.post('/api/reset-password', async (req, res) => {
  try {
    const raw      = String(req.body.token    || '');
    const password = String(req.body.password || '');

    if (!/^[a-f0-9]{64}$/.test(raw)) return res.status(400).json({ ok: false, error: 'Некорректный токен' });
    if (!isStrongPassword(password)) return res.status(400).json({ ok: false, error: 'Пароль не соответствует требованиям' });

    const tokenHash = sha256hex(raw);
    const client = await pool.connect();
    try {
      await client.query('BEGIN');

      // Блокируем токен от Race Condition (FOR UPDATE)
      const tk = await client.query(
        `SELECT id, user_id FROM password_setup_tokens
          WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()
          FOR UPDATE`,
        [tokenHash]
      );
      if (tk.rowCount === 0) {
        await client.query('ROLLBACK');
        return res.status(400).json({ ok: false, error: 'Ссылка недействительна или истекла' });
      }

      const userId  = tk.rows[0].user_id;
      const tokenId = tk.rows[0].id;

      // Проверяем, чтобы новый пароль не совпал со старым
      const userRes = await client.query('SELECT password_hash FROM users WHERE id = $1', [userId]);
      const currentHash = userRes.rows[0]?.password_hash;
      if (currentHash) {
        const isSame = await bcrypt.compare(password, currentHash);
        if (isSame) {
          await client.query('ROLLBACK');
          return res.status(400).json({ ok: false, error: 'Новый пароль не должен совпадать со старым паролем' });
        }
      }

      const hash    = await bcrypt.hash(password, BCRYPT_COST);

      // Меняем хеш пароля
      await client.query('UPDATE users SET password_hash = $1 WHERE id = $2', [hash, userId]);

      // Закрываем токен
      await client.query('UPDATE password_setup_tokens SET used_at = now() WHERE id = $1', [tokenId]);

      // Безопасность: уничтожаем абсолютно все активные сессии пользователя в системе
      await client.query('DELETE FROM refresh_tokens WHERE user_id = $1', [userId]);

      await client.query('COMMIT');
      return res.json({ ok: true });
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
  } catch (err) {
    console.error('[reset-password] error:', err);
    return res.status(500).json({ ok: false, error: 'Внутренняя ошибка сервера' });
  }
});

// ------------------- API: Вход (Аутентификация) -------------------
app.post('/api/login', loginLimiter, async (req, res) => {
  try {
    const email    = String(req.body.email || '').trim().toLowerCase();
    const password = String(req.body.password || '');

    if (!email || !password) {
      return res.status(400).json({ ok: false, error: 'Email и пароль обязательны' });
    }

    const result = await pool.query(
      'SELECT id, name, email, password_hash, status FROM users WHERE email = $1',
      [email]
    );

    if (result.rowCount === 0) {
      return res.status(401).json({ ok: false, error: 'Неверный email или пароль' });
    }

    const user = result.rows[0];

    if (user.status !== 'active') {
      return res.status(403).json({ ok: false, error: 'Учетная запись не активирована или заблокирована' });
    }

    const passwordMatch = await bcrypt.compare(password, user.password_hash);
    if (!passwordMatch) {
      return res.status(401).json({ ok: false, error: 'Неверный email или пароль' });
    }

    // Генерируем Access Token (короткоживущий JWT)
    const accessToken = jwt.sign(
      { userId: user.id, email: user.email, name: user.name },
      JWT_SECRET,
      { expiresIn: '15m' }
    );

    // Генерируем непрозрачный случайный Refresh Token (криптостойкий)
    const rawRefreshToken = crypto.randomBytes(32).toString('hex');
    const refreshTokenHash = sha256hex(rawRefreshToken);
    const sessionStartedAt = new Date();
    const expiresAt = computeRefreshExpiry(sessionStartedAt.getTime());

    // Сохраняем хеш рефреш-токена в БД
    await pool.query(
      'INSERT INTO refresh_tokens (user_id, token_hash, expires_at, session_started_at) VALUES ($1, $2, $3, $4)',
      [user.id, refreshTokenHash, expiresAt, sessionStartedAt]
    );

    // Логируем успешный вход в систему
    await pool.query('UPDATE users SET last_login_at = now() WHERE id = $1', [user.id]);

    // Отправляем рефреш-токен в безопасной куке, а access-токен в JSON ответе
    res.cookie('refreshToken', rawRefreshToken, cookieWithExpiry(expiresAt));
    return res.json({ ok: true, accessToken, user: { name: user.name, email: user.email } });

  } catch (err) {
    console.error('[login] error:', err);
    return res.status(500).json({ ok: false, error: 'Внутренняя ошибка сервера' });
  }
});

// ------------------- API: Обновление пары токенов (Refresh) -------------------
app.post('/api/refresh', async (req, res) => {
  try {
    const rawRefreshToken = req.cookies.refreshToken;
    if (!rawRefreshToken) return res.status(401).json({ ok: false, error: 'Токен возобновления отсутствует' });

    const tokenHash = sha256hex(rawRefreshToken);

    const client = await pool.connect();
    try {
      await client.query('BEGIN');

      const tokenResult = await client.query(
        `SELECT id, user_id, session_started_at FROM refresh_tokens 
         WHERE token_hash = $1 AND expires_at > now() 
         FOR UPDATE`,
        [tokenHash]
      );

      if (tokenResult.rowCount === 0) {
        await client.query('ROLLBACK');
        return res.status(401).json({ ok: false, error: 'Токен недействителен или истёк' });
      }

      const currentTokenId  = tokenResult.rows[0].id;
      const userId          = tokenResult.rows[0].user_id;
      const sessionStartedAt = tokenResult.rows[0].session_started_at;

      const userResult = await client.query(
        'SELECT id, name, email, status FROM users WHERE id = $1',
        [userId]
      );
      
      if (userResult.rowCount === 0 || userResult.rows[0].status !== 'active') {
        await client.query('ROLLBACK');
        return res.status(403).json({ ok: false, error: 'Пользователь недоступен' });
      }

      const user = userResult.rows[0];

      const newAccessToken = jwt.sign(
        { userId: user.id, email: user.email, name: user.name },
        JWT_SECRET,
        { expiresIn: '15m' }
      );

      await client.query('DELETE FROM refresh_tokens WHERE id = $1', [currentTokenId]);

      const newRawRefreshToken = crypto.randomBytes(32).toString('hex');
      const newRefreshTokenHash = sha256hex(newRawRefreshToken);
      const expiresAt = computeRefreshExpiry(new Date(sessionStartedAt).getTime());

      await client.query(
        'INSERT INTO refresh_tokens (user_id, token_hash, expires_at, session_started_at) VALUES ($1, $2, $3, $4)',
        [user.id, newRefreshTokenHash, expiresAt, sessionStartedAt]
      );

      await client.query('COMMIT');

      res.cookie('refreshToken', newRawRefreshToken, cookieWithExpiry(expiresAt));
      return res.json({ ok: true, accessToken: newAccessToken });

    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
  } catch (err) {
    console.error('[refresh] error:', err);
    return res.status(500).json({ ok: false, error: 'Внутренняя ошибка сервера' });
  }
});

// ------------------- API: Выход (Logout) -------------------
app.post('/api/logout', async (req, res) => {
  try {
    const rawRefreshToken = req.cookies.refreshToken;
    if (rawRefreshToken) {
      const tokenHash = sha256hex(rawRefreshToken);
      await pool.query('DELETE FROM refresh_tokens WHERE token_hash = $1', [tokenHash]);
    }
    res.clearCookie('refreshToken', { ...REFRESH_COOKIE_OPTIONS, maxAge: 0 });
    return res.json({ ok: true });
  } catch (err) {
    console.error('[logout] error:', err);
    return res.status(500).json({ ok: false, error: 'Внутренняя ошибка сервера' });
  }
});

// ------------------- Старт -------------------
app.listen(PORT, () => {
  console.log(`Uchet auth server with JWT listening on ${PORT}`);
});