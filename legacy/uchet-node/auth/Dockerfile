FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
# Зависимости
COPY auth/package.json auth/package-lock.json* ./
RUN npm install --omit=dev && npm cache clean --force
# Исходники сервиса
COPY auth/ .
# Общий сайдбар и тема
COPY shared/ ./shared/
# Непривилегированный пользователь
RUN addgroup -g 1001 app && adduser -D -u 1001 -G app app && chown -R app:app /app
USER app
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:3000/register || exit 1
CMD ["node", "server.js"]
