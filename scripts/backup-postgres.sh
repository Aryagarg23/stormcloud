#!/usr/bin/env sh
set -eu

umask 077

usage() {
  echo "Usage: $0 [OUTPUT.dump]" >&2
  exit 2
}

[ "$#" -le 1 ] || usage
command -v docker >/dev/null 2>&1 || {
  echo "docker is required" >&2
  exit 1
}

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
output=${1:-"backups/postgres/stormcloud-${timestamp}.dump"}
case "$output" in
  *.dump) ;;
  *)
    echo "backup path must end in .dump" >&2
    exit 2
    ;;
esac

output_dir=$(dirname "$output")
mkdir -p "$output_dir"
if [ -e "$output" ]; then
  echo "refusing to overwrite existing backup: $output" >&2
  exit 1
fi

partial="${output}.partial"
trap 'rm -f -- "$partial"' EXIT HUP INT TERM

docker compose exec -T postgres sh -eu -c '
  exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --compress=9 --no-owner --no-privileges
' >"$partial"

test -s "$partial"
mv "$partial" "$output"
trap - EXIT HUP INT TERM
echo "PostgreSQL backup written to $output"
