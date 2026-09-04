# Stormcloud

Stormcloud is a distributed, provenance-preserving evidence backend for individual research signals
and ordered or unordered bundles. Human input, source documents, deterministic NLP, highlights,
model outputs, evidence recipes, embeddings, and graph edges are stored as separate versioned layers.

## Quick start

1. Copy `.env.example` to `.env` and replace every development secret.
2. Start the development stack: `docker compose --profile dev up --build -d`.
3. Bootstrap the first admin once:
   `docker compose --profile init run --rm bootstrap-admin`.
4. Open the API documentation at <http://localhost:8080/docs> and Mailpit at
   <http://localhost:8025>.

Development mode uses deterministic fake fetching and model inference. Set
`STORMCLOUD_MODEL_GATEWAY_FAKE=false` and configure the model endpoint variables to use the
GPU-box services.

## Services

The same backend image runs the API, pipeline controller, fetch, NLP, LLM, embedding, graph, and
mail roles. PostgreSQL/pgvector, NATS JetStream, and MinIO are independent infrastructure
containers. No service relies on a shared filesystem.

See [deployment](docs/deployment.md), [API](http://localhost:8080/docs), and
[gpu-box inference](docs/gpu-box-inference.md).

Vercel is intentionally reserved for the frontend and is not part of the backend deployment.
