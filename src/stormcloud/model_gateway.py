import asyncio
import hashlib
import json
import math
import os
import re
from enum import StrEnum
from typing import Any
import httpx
import jsonschema
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from .config import get_settings
from .model_registry import ModelProfile, ModelRegistry, ModelRegistryError
from .observability import install_observability

class EmbeddingPurpose(StrEnum):
    QUERY = "query"
    CORPUS = "corpus"
    EVIDENCE = "evidence"
    SOURCE = "source"
    BUNDLE = "bundle"

class ChatRequest(BaseModel):
    task: str
    payload: dict[str, Any]

class EmbeddingRequest(BaseModel):
    task: str
    texts: list[str] = Field(min_length=1)
    purpose: EmbeddingPurpose = EmbeddingPurpose.CORPUS

class GatewayResponse(BaseModel):
    output: Any
    metadata: dict[str, Any]

class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    metadata: dict[str, Any]

def _parse_json(text: str) -> Any:
    return json.loads(text.strip())

def _validate_exact_spans(value: Any, payload: dict[str, Any]) -> None:
    if isinstance(value, list):
        for item in value:
            _validate_exact_spans(item, payload)
    elif isinstance(value, dict):
        if {"text", "start", "end"} <= value.keys():
            source = payload.get(str(value.get("source_field", "description_verbatim")))
            if not isinstance(source, str) or source[value["start"]:value["end"]] != value["text"]:
                raise ValueError("model returned text that is not an exact source span")
        for item in value.values():
            _validate_exact_spans(item, payload)

def validate_structured_output(value: Any, schema: dict[str, Any],
                               payload: dict[str, Any]) -> None:
    jsonschema.validate(value, schema)
    _validate_exact_spans(value, payload)
    if isinstance(value, dict) and "sentence_ids" in value:
        valid = {str(s["id"]) for s in payload.get("segments", [])}
        if any(item not in valid for item in value["sentence_ids"]):
            raise ValueError("model selected an unknown sentence id")

def _fake_vector(text: str, dimensions: int) -> list[float]:
    values: list[float] = []
    counter = 0
    while len(values) < dimensions:
        digest = hashlib.sha256(f"{counter}|{text}".encode()).digest()
        values.extend((byte - 127.5) / 127.5 for byte in digest)
        counter += 1
    values = values[:dimensions]
    norm = math.sqrt(sum(value * value for value in values)) or 1
    return [value / norm for value in values]

def _span_matches(text: str, pattern: str, kind: str) -> list[dict[str, Any]]:
    return [{"text": m.group(), "start": m.start(), "end": m.end(),
             "source_field": "description_verbatim", "kind": kind}
            for m in re.finditer(pattern, text)]

def _fake_chat(task: str, payload: dict[str, Any]) -> Any:
    if task == "highlighting":
        words = set(re.findall(r"[a-z0-9]{4,}", str(payload.get("description_verbatim", "")).lower()))
        ranked = [(len(words & set(re.findall(r"[a-z0-9]{4,}", s["text"].lower()))), s["id"])
                  for s in payload.get("segments", [])]
        return {"sentence_ids": [sid for score, sid in sorted(ranked, reverse=True)
                                if score > 0][:5]}
    if task == "extraction":
        text = str(payload.get("description_verbatim", ""))
        return {"claims": _span_matches(text, r"[^.!?\n]+(?:[.!?]|$)", "claim")[:32],
                "numbers": _span_matches(text, r"(?<!\w)(?:\d[\d,]*)(?:\.\d+)?%?", "number"),
                "dates": _span_matches(text, r"\b\d{4}-\d{2}-\d{2}\b", "date")}
    raise ValueError(f"fake chat has no task {task}")

class ModelGateway:
    def __init__(self, registry: ModelRegistry, fake: bool = False):
        self.registry, self.fake = registry, fake
        self.client = httpx.AsyncClient()

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, profile: ModelProfile, path: str,
                       body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {profile.api_key()}"} if profile.api_key() else {}
        error: Exception | None = None
        for attempt in range(profile.retries + 1):
            try:
                response = await self.client.post(f"{profile.base_url}{path}", json=body,
                                                  headers=headers, timeout=profile.timeout_seconds)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                error = exc
                if attempt < profile.retries:
                    await asyncio.sleep(min(0.25 * (2 ** attempt), 2))
        raise RuntimeError("model request exhausted retries") from error

    async def structured(self, task: str, payload: dict[str, Any]) -> GatewayResponse:
        profile, prompt = self.registry.profile_for(task), self.registry.prompt_for(task)
        if self.fake:
            output = _fake_chat(task, payload)
        else:
            body = {"model": profile.model,
                    "messages": [{"role": "system", "content": prompt.system_prompt},
                                 {"role": "user", "content": json.dumps(payload)}],
                    "response_format": {"type": "json_schema",
                        "json_schema": {"name": "stormcloud_result", "strict": True,
                                        "schema": prompt.response_schema}}}
            for key in ("temperature", "top_p", "max_tokens"):
                value = getattr(profile, key)
                if value is not None:
                    body[key] = value
            result = await self._request(profile, "/chat/completions", body)
            output = _parse_json(result["choices"][0]["message"]["content"])
        validate_structured_output(output, prompt.response_schema, payload)
        return GatewayResponse(output=output, metadata=self.registry.metadata(task))

    async def embed(self, task: str, texts: list[str],
                    purpose: EmbeddingPurpose) -> EmbeddingResponse:
        profile = self.registry.profile_for(task)
        if profile.kind != "embedding" or profile.dimensions is None:
            raise ModelRegistryError("task is not an embedding task")
        if len(texts) > profile.batch_size:
            raise ValueError("embedding batch is too large")
        prepared = [profile.query_prefix + text if purpose == EmbeddingPurpose.QUERY else text
                    for text in texts]
        if self.fake:
            vectors = [_fake_vector(text, profile.dimensions) for text in prepared]
        else:
            result = await self._request(profile, "/embeddings",
                                         {"model": profile.model, "input": prepared})
            vectors = [row["embedding"] for row in sorted(result["data"],
                       key=lambda row: row.get("index", 0))]
        if len(vectors) != len(texts) or any(len(vector) != profile.dimensions for vector in vectors):
            raise ValueError("embedding service returned the wrong dimensions")
        return EmbeddingResponse(embeddings=vectors,
            metadata=self.registry.metadata(task) |
                     {"purpose": purpose.value,
                      "query_prefix_applied": purpose == EmbeddingPurpose.QUERY})

class ModelGatewayClient:
    def __init__(self, base_url: str, timeout_seconds: float = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.client = httpx.AsyncClient()

    async def close(self) -> None:
        await self.client.aclose()

    async def structured(self, task: str, payload: dict[str, Any]) -> GatewayResponse:
        response = await self.client.post(f"{self.base_url}/v1/chat",
            json={"task": task, "payload": payload}, timeout=self.timeout_seconds)
        response.raise_for_status()
        return GatewayResponse.model_validate(response.json())

    async def embed(self, task: str, texts: list[str],
                    purpose: EmbeddingPurpose) -> EmbeddingResponse:
        response = await self.client.post(f"{self.base_url}/v1/embeddings",
            json={"task": task, "texts": texts, "purpose": purpose.value},
            timeout=self.timeout_seconds)
        response.raise_for_status()
        return EmbeddingResponse.model_validate(response.json())

def create_app() -> FastAPI:
    settings = get_settings()
    gateway = ModelGateway(ModelRegistry.load(settings.model_config_path, settings.prompt_root),
                           settings.model_gateway_fake)
    application = FastAPI(title="Stormcloud Model Gateway", version="0.1.0")
    application.state.gateway = gateway
    install_observability(application)

    @application.get("/health/ready")
    async def ready():
        return {"status": "ready"}

    @application.post("/v1/chat", response_model=GatewayResponse)
    async def chat(request: ChatRequest):
        try:
            return await gateway.structured(request.task, request.payload)
        except (ValueError, ModelRegistryError, jsonschema.ValidationError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @application.post("/v1/embeddings", response_model=EmbeddingResponse)
    async def embeddings(request: EmbeddingRequest):
        try:
            return await gateway.embed(request.task, request.texts, request.purpose)
        except (ValueError, ModelRegistryError) as exc:
            raise HTTPException(422, str(exc)) from exc
    return application

app = create_app()
