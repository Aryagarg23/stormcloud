# Stormcloud source-extractor adapter

This service wraps the pinned vendor/source-extractor submodule behind
Stormcloud's stable POST /v1/fetch contract. It receives no PostgreSQL, NATS,
or S3 credentials. The Stormcloud fetch worker owns persistence and provenance.

The adapter adds controls the upstream currently lacks: internal-token
authentication, DNS and redirect-aware SSRF blocking, standard TLS
verification, bounded payloads, deterministic normalization, canonical URLs,
and exact-offset segments.

Build it after initializing submodules:

    git submodule update --init --recursive
    docker compose --profile full build source-extractor

Do not publish port 8090. Only the internal Docker network should reach this
service. Set the same high-entropy STORMCLOUD_FETCHER_TOKEN for the adapter and
Stormcloud workers. Upstream updates must be reviewed and pinned by moving the
submodule commit explicitly.
