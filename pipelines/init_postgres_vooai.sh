#!/usr/bin/env bash
# Cria database `vooai` no Postgres FourDev e aplica schema.
# Uso local (docker SDR):
#   ./pipelines/init_postgres_vooai.sh
# Box:
#   POSTGRES_HOST=... POSTGRES_USER=sdr ./pipelines/init_postgres_vooai.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${POSTGRES_HOST:-127.0.0.1}"
PORT="${POSTGRES_PORT:-5432}"
USER="${POSTGRES_USER:-sdr}"
PASS="${POSTGRES_PASSWORD:-sdr_dev_password}"
export PGPASSWORD="$PASS"

echo "→ CREATE DATABASE vooai em ${HOST}:${PORT} (user=${USER})"
psql -h "$HOST" -p "$PORT" -U "$USER" -d postgres -v ON_ERROR_STOP=0 \
  -c "CREATE DATABASE vooai OWNER ${USER};" || true

echo "→ schema em vooai"
psql -h "$HOST" -p "$PORT" -U "$USER" -d vooai -v ON_ERROR_STOP=1 \
  -f "$ROOT/pipelines/sql/02_schema.sql"

echo "OK. Exporte:"
echo "  export VOOAI_DATABASE_URL=postgresql://${USER}:***@${HOST}:${PORT}/vooai"
