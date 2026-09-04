#!/usr/bin/env sh
set -eu

MC_IMAGE="minio/mc:RELEASE.2025-04-16T18-13-26Z"
BUCKETS="stormcloud-source-raw stormcloud-source-normalized stormcloud-derived"

read_dotenv() {
  key=$1
  fallback=$2
  value=$(awk -v key="$key" 'index($0, key "=") == 1 { print substr($0, length(key) + 2); exit }' .env 2>/dev/null || true)
  if [ -n "$value" ]; then printf %s "$value"; else printf %s "$fallback"; fi
}

usage() {
  echo "Usage: $0 BACKUP_DIRECTORY --confirm stormcloud" >&2
  exit 2
}

[ "$#" -eq 3 ] || usage
source_dir=$1
[ "$2" = "--confirm" ] || usage
[ "$3" = "stormcloud" ] || {
  echo "confirmation target must be exactly: stormcloud" >&2
  exit 2
}
[ -f "$source_dir/MANIFEST.txt" ] || {
  echo "missing Stormcloud MinIO backup manifest: $source_dir/MANIFEST.txt" >&2
  exit 1
}
grep -qx 'format=stormcloud-minio-mirror-v1' "$source_dir/MANIFEST.txt" || {
  echo "unrecognized backup format" >&2
  exit 1
}
for bucket in $BUCKETS; do
  [ -d "$source_dir/$bucket" ] || {
    echo "backup is missing bucket directory: $bucket" >&2
    exit 1
  }
done

source_abs=$(CDPATH= cd -- "$source_dir" && pwd)
STORMCLOUD_S3_ACCESS_KEY=${STORMCLOUD_S3_ACCESS_KEY:-$(read_dotenv STORMCLOUD_S3_ACCESS_KEY stormcloud)}
STORMCLOUD_S3_SECRET_KEY=${STORMCLOUD_S3_SECRET_KEY:-$(read_dotenv STORMCLOUD_S3_SECRET_KEY "")}
export STORMCLOUD_S3_ACCESS_KEY STORMCLOUD_S3_SECRET_KEY
[ -n "$STORMCLOUD_S3_SECRET_KEY" ] || {
  echo "STORMCLOUD_S3_SECRET_KEY must be set or present in .env" >&2
  exit 1
}

echo "Restoring objects from $source_dir into the three Stormcloud buckets." >&2
echo "Existing keys may be overwritten; unrelated keys are retained." >&2

docker run --rm --network stormcloud --user "$(id -u):$(id -g)" --env HOME=/tmp --env STORMCLOUD_S3_ACCESS_KEY --env STORMCLOUD_S3_SECRET_KEY --volume "$source_abs:/backup:ro" --entrypoint /bin/sh "$MC_IMAGE" -eu -c '
    mc alias set stormcloud http://minio:9000 "$STORMCLOUD_S3_ACCESS_KEY" "$STORMCLOUD_S3_SECRET_KEY" >/dev/null
    for bucket in stormcloud-source-raw stormcloud-source-normalized stormcloud-derived; do
      mc stat "stormcloud/$bucket" >/dev/null
      mc mirror --overwrite --preserve "/backup/$bucket" "stormcloud/$bucket"
    done
  '

echo "MinIO restore completed."
