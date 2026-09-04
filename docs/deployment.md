# Deployment

Stormcloud runs as a private multi-container backend on the GPU box. The public web application is
deployed to Vercel and calls one authenticated API origin exposed through Tailscale Funnel. PostgreSQL,
NATS, MinIO, the extractor, workers, model gateway, and Mailpit have no public ports.

## Live endpoints

- Frontend: https://stormcloud-theta.vercel.app
- API: https://gpu-box.tail54252.ts.net
- Readiness: https://gpu-box.tail54252.ts.net/health/ready

The API allows only the exact Vercel origin, validates the HTTP Host header, rate-limits authentication,
disables production OpenAPI routes, and emits restrictive browser security headers. Funnel terminates TLS
and proxies only to the API's loopback-bound port.

## Initial production launch

From the repository root:

```bash
./scripts/configure-production-env.sh \
  https://stormcloud-theta.vercel.app \
  gpu-box.tail54252.ts.net \
  garg.arya@gmail.com \
  18080

docker compose down
docker compose -p stormcloud-prod --profile full --profile init --profile mail up --build -d
docker compose -p stormcloud-prod ps
```

The configuration script creates fresh high-entropy service secrets in ignored files with mode `0600`.
The one-time administrator password is in ignored `bootstrap-credentials.txt`; it is not committed.
The bootstrap command refuses to create another administrator after the first one exists.

On Windows, publish the loopback API and inspect its state:

```powershell
tailscale.exe funnel --bg --https=443 http://127.0.0.1:18080
tailscale.exe funnel status
```

Stop public access with `tailscale.exe funnel reset`. Do not expose Compose infrastructure ports or
point Funnel at MinIO, PostgreSQL, NATS, model services, Mailpit, or the extractor.

## Frontend

The Vercel project root is `frontend` and its production environment contains:

```text
VITE_API_BASE_URL=https://gpu-box.tail54252.ts.net/v1
```

Deploy with `cd frontend && vercel deploy --prod --yes`. The backend is intentionally not deployed to
Vercel.

## Model and prompt versions

All inference goes through `model-gateway`. Model endpoints, IDs, dimensions, task bindings, decoding,
timeouts, retries, concurrency, batching, pooling, and query-only embedding prefixes are configured in
`config/models.yaml`. Prompts and response schemas live under
`config/prompts/<task>/<model-profile>/<version>/`. Configuration and prompt hashes are saved with
derived artifacts.

The default production configuration uses the existing Gemma and Qwen services on the private network.
Set `STORMCLOUD_MODEL_GATEWAY_FAKE=true` only for deterministic local and CI runs.

## Extractor

Initialize the pinned extractor source after cloning:

```bash
git submodule update --init --recursive
```

The private `source-extractor` container has no database, object-store, or broker credentials. It accepts
only token-authenticated requests from the fetch worker and performs TLS, SSRF, redirect, and payload-size
validation before returning the stable fetch contract.

## Mail

The `mail` profile runs loopback-only Mailpit for immediate local operation. Before inviting external
researchers, replace `STORMCLOUD_SMTP_HOST`, port, sender, and provider credentials with a trusted SMTP
relay, then recreate the mailer. Never publish Mailpit through Funnel.

## Moving roles between hosts

Use `infra`, `core`, `workers`, `extractor`, `mail`, and `init` profiles to split services.
Override database, NATS, S3, fetcher, model-gateway, and SMTP addresses through environment variables.
Keep stateful services on durable storage; lightweight stateless workers can move to ARM64 hosts once
their host has binfmt/QEMU or native ARM hardware.

## Operations

See [backup and restore](backup-and-restore.md) for PostgreSQL and object-store procedures. Check service
health with `docker compose -p stormcloud-prod ps`, API readiness at `/health/ready`, and metrics at the
private `/metrics` endpoint. Logs are structured JSON and can be shipped by the container runtime.
