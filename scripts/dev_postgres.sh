#!/usr/bin/env bash
# Starts a throwaway local Postgres 16 on port 5499 for development and tests (Lakebase is Postgres, so the
# same SQL runs in both). Requires postgresql-16 binaries. Data lives in ./local_data/pg.
set -euo pipefail
PGBIN=${PGBIN:-/usr/lib/postgresql/16/bin}
DATA=${PG_DATA:-$(pwd)/local_data/pg}
PORT=${PG_PORT:-5499}
if [ ! -d "$DATA" ]; then
  mkdir -p "$DATA"
  "$PGBIN/initdb" -D "$DATA" -U pim --auth=trust >/dev/null
fi
"$PGBIN/pg_ctl" -D "$DATA" -l "$DATA/server.log" -o "-p $PORT -k /tmp -c listen_addresses=localhost" start
for db in pim pim_test; do
  psql -h localhost -p "$PORT" -U pim -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 || \
    psql -h localhost -p "$PORT" -U pim -d postgres -c "CREATE DATABASE $db"
done
echo "Postgres ready: postgresql+psycopg://pim@localhost:$PORT/pim"
