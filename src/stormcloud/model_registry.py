import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
import yaml

class ModelRegistryError(ValueError):
    pass

def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def _hash(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()

_ENV = re.compile(r"^\$\{([A-Z][A-Z0-9_]*)(?::-([^}]*))?\}$")

def _environment(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _environment(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_environment(item) for item in value]
    if not isinstance(value, str):
        return value
    match = _ENV.match(value)
    if not match:
        return value
    name, default = match.groups()
    result = os.getenv(name, default)
    if result is None:
        raise ModelRegistryError(f"required environment variable {name} is not set")
    return result

@dataclass(frozen=True, slots=True)
class ModelProfile:
    name: str
    kind: Literal["chat", "embedding"]
    base_url: str
    model: str
    api_key_env: str | None
    timeout_seconds: float
    retries: int
    concurrency: int
    batch_size: int
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    dimensions: int | None = None
    pooling: str | None = None
    query_prefix: str = ""

    @classmethod
    def parse(cls, name: str, raw: dict[str, Any]) -> "ModelProfile":
        kind = raw.get("kind")
        if kind not in ("chat", "embedding"):
            raise ModelRegistryError(f"profile {name!r} has invalid kind")
        dimensions = raw.get("dimensions")
        if kind == "embedding" and (not isinstance(dimensions, int) or dimensions < 1):
            raise ModelRegistryError(f"embedding profile {name!r} needs positive dimensions")
        return cls(name=name, kind=kind, base_url=str(raw["base_url"]).rstrip("/"),
                   model=str(raw["model"]), api_key_env=raw.get("api_key_env"),
                   timeout_seconds=float(raw.get("timeout_seconds", 60)),
                   retries=int(raw.get("retries", 2)),
                   concurrency=int(raw.get("concurrency", 4)),
                   batch_size=int(raw.get("batch_size", 32)),
                   temperature=float(raw["temperature"]) if "temperature" in raw else None,
                   top_p=float(raw["top_p"]) if "top_p" in raw else None,
                   max_tokens=int(raw["max_tokens"]) if "max_tokens" in raw else None,
                   dimensions=dimensions, pooling=raw.get("pooling"),
                   query_prefix=str(raw.get("query_prefix", "")))

    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env) if self.api_key_env else None

@dataclass(frozen=True, slots=True)
class TaskBinding:
    name: str
    profile: str
    prompt_version: str | None = None

@dataclass(frozen=True, slots=True)
class PromptArtifact:
    task: str
    profile: str
    version: str
    system_prompt: str
    response_schema: dict[str, Any]
    prompt_hash: str
    schema_hash: str

class ModelRegistry:
    def __init__(self, *, profiles: dict[str, ModelProfile], tasks: dict[str, TaskBinding],
                 prompt_root: Path, config_hash: str):
        self.profiles = profiles
        self.tasks = tasks
        self.prompt_root = prompt_root
        self.config_hash = config_hash
        self._prompts: dict[str, PromptArtifact] = {}
        for task, binding in tasks.items():
            if binding.profile not in profiles:
                raise ModelRegistryError(f"task {task!r} names unknown profile {binding.profile!r}")
            if binding.prompt_version:
                self._prompts[task] = self._load_prompt(task, binding)

    @classmethod
    def load(cls, path: str | Path, prompt_root: str | Path) -> "ModelRegistry":
        raw = _environment(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
        if raw.get("version") != 1:
            raise ModelRegistryError("models.yaml version must be 1")
        profiles = {name: ModelProfile.parse(name, value)
                    for name, value in raw.get("profiles", {}).items()}
        tasks = {name: TaskBinding(name, str(value["profile"]), value.get("prompt_version"))
                 for name, value in raw.get("tasks", {}).items()}
        if not profiles or not tasks:
            raise ModelRegistryError("at least one profile and task are required")
        return cls(profiles=profiles, tasks=tasks, prompt_root=Path(prompt_root),
                   config_hash=_hash(_canonical(raw)))

    def profile_for(self, task: str) -> ModelProfile:
        try:
            return self.profiles[self.tasks[task].profile]
        except KeyError as exc:
            raise ModelRegistryError(f"unknown model task {task!r}") from exc

    def prompt_for(self, task: str) -> PromptArtifact:
        try:
            return self._prompts[task]
        except KeyError as exc:
            raise ModelRegistryError(f"task {task!r} has no prompt") from exc

    def metadata(self, task: str) -> dict[str, Any]:
        profile = self.profile_for(task)
        prompt = self._prompts.get(task)
        return {"task": task, "profile": profile.name, "model": profile.model,
                "dimensions": profile.dimensions, "config_hash": self.config_hash,
                "prompt_version": prompt.version if prompt else None,
                "prompt_hash": prompt.prompt_hash if prompt else None,
                "schema_hash": prompt.schema_hash if prompt else None}

    def _load_prompt(self, task: str, binding: TaskBinding) -> PromptArtifact:
        directory = self.prompt_root / task / binding.profile / str(binding.prompt_version)
        prompt_path, schema_path = directory / "system.txt", directory / "schema.json"
        if not prompt_path.is_file() or not schema_path.is_file():
            raise ModelRegistryError(f"missing prompt artifact at {directory}")
        prompt = prompt_path.read_text(encoding="utf-8").strip()
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if not prompt or not isinstance(schema, dict):
            raise ModelRegistryError(f"invalid prompt artifact at {directory}")
        return PromptArtifact(task, binding.profile, str(binding.prompt_version), prompt, schema,
                              _hash(prompt), _hash(_canonical(schema)))
