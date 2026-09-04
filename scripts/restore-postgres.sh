#!/usr/bin/env sh
set -eu

usage() {
  echo "Usage: $0 BACKUP.dump --confirm stormcloud" >&2
  exit 2
}

[ "$#" -eq 3 ] || usage
archive=$1
[ "$2" = "--confirm" ] || usage
[ "$3" = "stormcloud" ] || {
  echo "confirmation target must be exactly: stormcloud" >&2
  exit 2
}
[ -f "$archive" ] || {
  echo "backup is not a regular file: $archive" >&2
  exit 1
}
[ -s "$archive" ] || {
  echo "backup is empty: $archive" >&2
  exit 1
}
command -v docker >/dev/null 2>&1 || {
  echo "docker is required" >&2
  exit 1
}

database=$(docker compose exec -T postgres sh -eu -c 'printf %s "$POSTGRES_DB"')
[ "$database" = "stormcloud" ] || {
  echo "refusing restore: container database is '$database', expected 'stormcloud'" >&2
  exit 1
}

echo "Restoring $archive into the Compose PostgreSQL database 'stormcloud'." >&2
echo "This replaces objects represented in the archive; API and workers should be stopped." >&2

docker compose exec -T postgres sh -eu -c '
  exec pg_restore --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --clean --if-exists --single-transaction --no-owner --no-privileges --exit-on-error
' <"$archive"

docker compose exec -T postgres sh -eu -c '
  exec psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --no-psqlrc --tuples-only --command="SELECT current_database();"
'
echo "PostgreSQL restore completed."
