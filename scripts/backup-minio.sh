#!/usr/bin/env sh
set -eu

umask 077
MC_IMAGE="minio/mc:RELEASE.2025-04-16T18-13-26Z"
BUCKETS="stormcloud-source-raw stormcloud-source-normalized stormcloud-derived"

read_dotenv() {
  key=$1
  fallback=$2
  value=$(awk -v key="$key" 'index($0, key "=") == 1 { print substr($0, length(key) + 2); exit }' .env 2>/dev/null || true)
  if [ -n "$value" ]; then printf %s "$value"; else printf %s "$fallback"; fi
}

usage() {
  echo "Usage: $0 [OUTPUT_DIRECTORY]" >&2
  exit 2
}

[ "$#" -le 1 ] || usage
command -v docker >/dev/null 2>&1 || {
  echo "docker is required" >&2
  exit 1
}

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
destination=${1:-"backups/minio/stormcloud-${timestamp}"}
[ ! -e "$destination" ] || {
  echo "refusing to overwrite existing backup: $destination" >&2
  exit 1
}

partial="${destination}.partial"
mkdir -p "$partial"
for bucket in $BUCKETS; do
  mkdir -p "$partial/$bucket"
done
partial_abs=$(CDPATH= cd -- "$partial" && pwd)
trap 'rm -rf -- "$partial"' EXIT HUP INT TERM

STORMCLOUD_S3_ACCESS_KEY=${STORMCLOUD_S3_ACCESS_KEY:-$(read_dotenv STORMCLOUD_S3_ACCESS_KEY stormcloud)}
STORMCLOUD_S3_SECRET_KEY=${STORMCLOUD_S3_SECRET_KEY:-$(read_dotenv STORMCLOUD_S3_SECRET_KEY "")}
export STORMCLOUD_S3_ACCESS_KEY STORMCLOUD_S3_SECRET_KEY
[ -n "$STORMCLOUD_S3_SECRET_KEY" ] || {
  echo "STORMCLOUD_S3_SECRET_KEY must be set or present in .env" >&2
  exit 1
}

docker run --rm --network stormcloud --user "$(id -u):$(id -g)" --env HOME=/tmp --env STORMCLOUD_S3_ACCESS_KEY --env STORMCLOUD_S3_SECRET_KEY --volume "$partial_abs:/backup" --entrypoint /bin/sh "$MC_IMAGE" -eu -c '
    mc alias set stormcloud http://minio:9000 "$STORMCLOUD_S3_ACCESS_KEY" "$STORMCLOUD_S3_SECRET_KEY" >/dev/null
    for bucket in stormcloud-source-raw stormcloud-source-normalized stormcloud-derived; do
      mc stat "stormcloud/$bucket" >/dev/null
      mc mirror --preserve "stormcloud/$bucket" "/backup/$bucket"
    done
  '

{
  echo "format=stormcloud-minio-mirror-v1"
  echo "created_at_utc=$timestamp"
  echo "mc_image=$MC_IMAGE"
  for bucket in $BUCKETS; do
    count=$(find "$partial/$bucket" -type f | wc -l | tr -d ' ')
    echo "objects.$bucket=$count"
  done
} >"$partial/MANIFEST.txt"

mkdir -p "$(dirname "$destination")"
mv "$partial" "$destination"
trap - EXIT HUP INT TERM
echo "MinIO mirror written to $destination"
