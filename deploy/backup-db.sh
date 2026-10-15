#!/usr/bin/env bash
#
# Резервная копия базы портала (только БД портала, не источник).
#
# Куда положить: /opt/portalprostoev/deploy/backup-db.sh
# Сделать исполняемым:  chmod +x deploy/backup-db.sh
# Запускать по расписанию — см. deploy/crontab.example
#
# Копии кладутся в /var/backups/portalprostoev и хранятся 30 дней.
# Пароль базы берётся из того же файла .env, что использует портал — вручную вводить не нужно.

set -euo pipefail

PROJECT_DIR="/opt/portalprostoev"
BACKUP_DIR="/var/backups/portalprostoev"
KEEP_DAYS=30

# Читаем реквизиты БД из .env (строки вида КЛЮЧ=значение).
ENV_FILE="${PROJECT_DIR}/.env"
DB_NAME="$(grep -E '^POSTGRES_DB='   "${ENV_FILE}" | cut -d= -f2-)"
DB_USER="$(grep -E '^POSTGRES_USER=' "${ENV_FILE}" | cut -d= -f2-)"
DB_PASS="$(grep -E '^POSTGRES_PASSWORD=' "${ENV_FILE}" | cut -d= -f2-)"
DB_HOST="$(grep -E '^POSTGRES_HOST=' "${ENV_FILE}" | cut -d= -f2-)"
DB_PORT="$(grep -E '^POSTGRES_PORT=' "${ENV_FILE}" | cut -d= -f2-)"

STAMP="$(date +%Y-%m-%d_%H-%M)"
FILE="${BACKUP_DIR}/${DB_NAME}_${STAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

# pg_dump делает снимок базы; gzip сжимает; пароль передаём через переменную окружения.
PGPASSWORD="${DB_PASS}" pg_dump \
    --host="${DB_HOST}" --port="${DB_PORT}" \
    --username="${DB_USER}" --dbname="${DB_NAME}" \
    --no-owner --no-privileges \
    | gzip > "${FILE}"

echo "Готово: ${FILE}"

# Удаляем копии старше KEEP_DAYS дней.
find "${BACKUP_DIR}" -name '*.sql.gz' -type f -mtime +"${KEEP_DAYS}" -delete
