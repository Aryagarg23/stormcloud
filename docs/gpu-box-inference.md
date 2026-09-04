# gpu-box inference stack

Host: **gpu-box** (`100.89.196.15`, `gpu-box.tail54252.ts.net`), WSL2 Ubuntu 26.04,
RTX 3090 Ti 24GB, standalone `dockerd` + NVIDIA Container Toolkit 1.20.

Two services, two containers (GPU vLLM + CPU llama.cpp — separate images, they
cannot merge into one container). Both `--restart unless-stopped` with weights
persisted on the WSL disk, so recreates never re-download.

## Ports

| Port | Service | Model | Backend | Measured |
|------|---------|-------|---------|----------|
| 8000 | vLLM OpenAI API (`/v1/*`, `/health`) | `dhruvil237/gemma-4-26B-A4B-it-W4A16` (26B MoE, 4B active, W4A16 Marlin) | GPU, `gpu-memory-utilization 0.90`, `max-model-len 32768` | solo ~147 tok/s, 8-way diverse ~538 tok/s agg |
| 8080 | llama.cpp server (`/v1/embeddings`, `/health`) | `Qwen/Qwen3-Embedding-4B-Q8_0` (2560 dims, `--pooling last`) | CPU, 26 threads | single ~210ms, batch ~4/s |
| 8081 | llama.cpp server (`/v1/embeddings`, `/health`) | `Qwen/Qwen3-Embedding-0.6B-Q8_0` (1024 dims, `--pooling last`) | CPU, 26 threads | single ~120-170ms, batch ~20/s, conc ~24/s agg |

Tailnet base URLs: `http://100.89.196.15:8000|8080|8081`.
Mirrored-networking WSL exposes all ports on the host IP directly.

MTEB Eng v2 (May 2025 snapshot): Qwen3-4B 74.60, Qwen3-0.6B 70.70,
stella-1.5B 69.43, gte-Qwen2-1.5B 67.20. The 0.6B beats every ~1.5B model while
running ~5x faster on CPU — it is the default pick; 4B for max quality on live
queries (too slow for bulk ingest at ~4/s).

## Embedding input contract (REQUIRED — Qwen3 is instruction-aware)

The servers embed raw text with no prefix of their own
(llama.cpp has no query-prefix setting), so callers MUST apply it.
Skipping the query instruction costs ~1-5% retrieval quality.

- **Documents (corpus): embed RAW text, no prefix.**
- **Queries: prefix with a task instruction, exactly:**
  `Instruct: <one-sentence task description>\nQuery: <text>`
- Default retrieval instruction (use unless the task needs its own):
  `Instruct: Given a web search query, retrieve relevant passages that answer the query`
- Write instructions in English even for non-English text (matches training).
- Both sides use `--pooling last` (server-side, already configured) — do NOT
  mean-pool client-side.

Example query input:
`Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: What is the capital of China?`

TEI was tried first for embeddings and abandoned: its ONNX/MKL backend throws
`Parameter N was incorrect on entry to HGEMM/SGEMM` on this CPU for the Qwen3
decoder shapes (fp16 and fp32 alike). llama.cpp has no MKL dependency.

## Docker run commands

LLM (GPU):

```bash
docker run -d --gpus all --ipc=host --restart unless-stopped \
  --name vllm-gemma -p 8000:8000 \
  -v /root/hfcache:/root/.cache/huggingface \
  vllm/vllm-openai:latest \
  --model dhruvil237/gemma-4-26B-A4B-it-W4A16 \
  --gpu-memory-utilization 0.90 --max-model-len 32768
```

Embeddings (CPU-only; note the absence of `--gpus`):

```bash
docker run -d --restart unless-stopped \
  --name llama-embed -p 8080:8080 -v /root/llamacpp-models:/models \
  ghcr.io/ggml-org/llama.cpp:server \
  -m /models/Qwen3-Embedding-4B-Q8_0.gguf \
  --embedding --pooling last --threads 26 -c 8192 --port 8080
```

Same pattern on 8081 for `llama-embed-small` with
`Qwen3-Embedding-0.6B-Q8_0.gguf` and `--port 8081`.

`--max-model-len 32768` is required on the LLM: native 262144 context needs
6.15 GiB KV but only ~2.8 GiB is free after the 15.1 GiB weights on 24GB VRAM;
vLLM refuses to start otherwise (it estimates ~85k as the ceiling).

## Auto-start chain

Windows logon -> `WSLKeepAlive` Run-key loop (`wsl sleep 120` on repeat,
self-healing) -> WSL boot -> systemd `dockerd` (enabled) -> all containers
(`unless-stopped`). Needs a user logon after a Windows reboot.

## Layout on this box

- `/home/source/scripts/` — bench scripts (`vllm-bench*.py`, `tei-bench*.py`,
  `llama-bench*.py`, all md5-verified against origin)
- `/home/source/venvs/` — designated home for Python venvs
- `/home/source/repos/stormcloud/` — this doc
- `/root/hfcache`, `/root/llamacpp-models` — persisted model weights (NOT in repos)
- Box SSH passwords: NOT in any repo (stored separately by owner)
