#!/bin/sh
# entrypoint.sh — Docker startup script for CareMed / ATRIMS
# ─────────────────────────────────────────────────────────────
# 1. Wait for MySQL to accept connections.
# 2. If the schema is absent (fresh volume): create all tables and
#    stamp the migration head so future `flask db upgrade` is safe.
# 3. If the schema already exists: run `flask db upgrade` to apply
#    any new migrations.
# 4. Start gunicorn.
# ─────────────────────────────────────────────────────────────

set -e

# ── 1. Wait for MySQL ──────────────────────────────────────────
# DATABASE_URL is expected to be set in the environment / .env file
# e.g. mysql+pymysql://user:pass@db:3306/caremed_db

# Extract host and port from DATABASE_URL (works for mysql+pymysql:// URIs)
DB_HOST=$(echo "$DATABASE_URL" | sed -n 's|.*://[^@]*@\([^:/]*\).*|\1|p')
DB_PORT=$(echo "$DATABASE_URL" | sed -n 's|.*://[^@]*@[^:/]*:\([0-9]*\)/.*|\1|p')
DB_PORT=${DB_PORT:-3306}

echo "[entrypoint] Waiting for MySQL at ${DB_HOST}:${DB_PORT} ..."
MAX_RETRIES=30
RETRY=0
until mysqladmin ping -h"${DB_HOST}" -P"${DB_PORT}" --silent 2>/dev/null; do
    RETRY=$((RETRY + 1))
    if [ "$RETRY" -ge "$MAX_RETRIES" ]; then
        echo "[entrypoint] ERROR: MySQL did not become ready after ${MAX_RETRIES} attempts. Aborting."
        exit 1
    fi
    echo "[entrypoint] MySQL not ready yet (attempt ${RETRY}/${MAX_RETRIES}). Retrying in 2 s ..."
    sleep 2
done
echo "[entrypoint] MySQL is ready."

# ── 2. Detect fresh vs existing schema ────────────────────────
# Run a tiny Python snippet that returns exit-code 0 when the
# 'alembic_version' table exists (i.e. migrations have run before)
# and exit-code 1 when it is absent (fresh volume).
python - <<'PYEOF'
import sys, os
from sqlalchemy import create_engine, inspect

url = os.environ["DATABASE_URL"]
engine = create_engine(url, pool_pre_ping=True)
inspector = inspect(engine)
tables = inspector.get_table_names()
if "alembic_version" in tables:
    print("[entrypoint] Existing schema detected (alembic_version present).")
    sys.exit(0)   # existing
else:
    print("[entrypoint] Fresh database -- no alembic_version table found.")
    sys.exit(1)   # fresh
PYEOF
SCHEMA_EXISTS=$?

# ── 3a. Fresh DB — create all tables then stamp ───────────────
if [ "$SCHEMA_EXISTS" -ne 0 ]; then
    echo "[entrypoint] Initialising schema with db.create_all() ..."
    python create_db.py
    echo "[entrypoint] Stamping migration head ..."
    flask db stamp head
    echo "[entrypoint] Schema initialised and stamped."
else
    # ── 3b. Existing DB — apply any pending migrations ────────
    echo "[entrypoint] Running flask db upgrade ..."
    flask db upgrade
    echo "[entrypoint] Migrations applied."
fi

# ── 4. Start gunicorn ─────────────────────────────────────────
echo "[entrypoint] Starting gunicorn ..."
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 2 \
    -k gevent \
    --worker-connections 1000 \
    --timeout 120 \
    --preload \
    --access-logfile - \
    --error-logfile - \
    app:app
