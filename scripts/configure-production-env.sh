#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "Usage: $0 <vercel-origin> <funnel-hostname> <admin-email> [api-port]" >&2
  exit 2
fi

vercel_origin="${1%/}"
funnel_host="${2%.}"
admin_email="$3"
api_port="${4:-18080}"

if [[ ! "$vercel_origin" =~ ^https://[A-Za-z0-9.-]+$ ]]; then
  echo "Vercel origin must be an https origin without a path" >&2
  exit 2
fi
if [[ ! "$funnel_host" =~ ^[A-Za-z0-9.-]+\.ts\.net$ ]]; then
  echo "Funnel hostname must be a ts.net hostname" >&2
  exit 2
fi
if [[ ! "$admin_email" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
  echo "Admin email is invalid" >&2
  exit 2
fi

command -v openssl >/dev/null || {
  echo "openssl is required" >&2
  exit 1
}

db_password="$(openssl rand -hex 32)"
nats_password="$(openssl rand -hex 32)"
s3_secret="$(openssl rand -hex 32)"
jwt_secret="$(openssl rand -hex 48)"
fetcher_token="$(openssl rand -hex 48)"
admin_password="$(openssl rand -hex 24)"

umask 077
env_tmp="$(mktemp .env.production.XXXXXX)"
credentials_tmp="$(mktemp bootstrap-credentials.XXXXXX)"
trap 'rm -f "$env_tmp" "$credentials_tmp"' EXIT

cat >"$env_tmp" <<EOF
STORMCLOUD_ENV=production
POSTGRES_PASSWORD=$db_password
STORMCLOUD_NETWORK_NAME=stormcloud-prod
NATS_USER=stormcloud
NATS_PASSWORD=$nats_password
STORMCLOUD_DATABASE_URL=postgresql+psycopg://stormcloud:$db_password@postgres:5432/stormcloud
STORMCLOUD_NATS_URL=nats://stormcloud:$nats_password@nats:4222
STORMCLOUD_S3_ENDPOINT_URL=http://minio:9000
STORMCLOUD_S3_ACCESS_KEY=stormcloud
STORMCLOUD_S3_SECRET_KEY=$s3_secret
STORMCLOUD_JWT_SECRET=$jwt_secret
STORMCLOUD_CORS_ORIGINS=$vercel_origin
STORMCLOUD_ALLOWED_HOSTS=$funnel_host,localhost,127.0.0.1,api
STORMCLOUD_PUBLIC_DOCS=false
STORMCLOUD_AUTH_RATE_LIMIT_PER_MINUTE=30
STORMCLOUD_INVITE_ACCEPT_URL=$vercel_origin/accept-invite
STORMCLOUD_SMTP_HOST=mailpit
STORMCLOUD_SMTP_PORT=1025
STORMCLOUD_SMTP_FROM=stormcloud@localhost
STORMCLOUD_FETCHER_BASE_URL=http://source-extractor:8090
STORMCLOUD_FETCHER_TOKEN=$fetcher_token
STORMCLOUD_FETCHER_MAX_BYTES=10485760
STORMCLOUD_FETCHER_RAW_MAX_BYTES=8388608
STORMCLOUD_MODEL_GATEWAY_URL=http://model-gateway:8085
STORMCLOUD_MODEL_CONFIG_PATH=/app/config/models.yaml
STORMCLOUD_PROMPT_ROOT=/app/config/prompts
STORMCLOUD_MODEL_GATEWAY_FAKE=false
STORMCLOUD_DEBUG_RETURN_INVITE_TOKEN=false
STORMCLOUD_SIMILARITY_THRESHOLD=0.72
STORMCLOUD_SIMILARITY_TOP_K=20
STORMCLOUD_API_PORT=$api_port
BOOTSTRAP_ADMIN_EMAIL=$admin_email
BOOTSTRAP_ADMIN_PASSWORD=$admin_password
EOF

cat >"$credentials_tmp" <<EOF
Stormcloud bootstrap administrator
Email: $admin_email
Password: $admin_password
Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

mv "$env_tmp" .env.production
cp .env.production .env
mv "$credentials_tmp" bootstrap-credentials.txt
chmod 600 .env.production .env bootstrap-credentials.txt
trap - EXIT
echo "Wrote .env, .env.production, and bootstrap-credentials.txt with mode 600."
