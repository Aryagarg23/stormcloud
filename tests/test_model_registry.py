from __future__ import annotations

import json
from pathlib import Path

import pytest

from stormcloud.model_registry import ModelRegistry, ModelRegistryError


def write_registry(tmp_path, *, prompt="Extract exact spans.", model="gemma"):
    prompt_dir = tmp_path / "prompts" / "extract" / "gemma-v1" / "v1"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / "system.txt").write_text(prompt, encoding="utf-8")
    (prompt_dir / "schema.json").write_text(
        json.dumps({"type": "object", "properties": {"spans": {"type": "array"}}}),
        encoding="utf-8",
    )
    config = tmp_path / "models.yaml"
    config.write_text(
        "\n".join(
            [
                "version: 1",
                "profiles:",
                "  gemma-v1:",
                "    kind: chat",
                "    base_url: ${TEST_MODEL_URL:-http://model:8000}",
                f"    model: {model}",
                "    temperature: 0",
                "tasks:",
                "  extract:",
                "    profile: gemma-v1",
                "    prompt_version: v1",
            ]
        ),
        encoding="utf-8",
    )
    return config, tmp_path / "prompts"


def test_registry_loads_versioned_prompt_and_records_stable_hashes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEST_MODEL_URL", "https://models.internal/v1")
    config, prompts = write_registry(tmp_path)

    first = ModelRegistry.load(config, prompts)
    second = ModelRegistry.load(config, prompts)

    assert first.profile_for("extract").base_url == "https://models.internal/v1"
    assert first.prompt_for("extract").system_prompt == "Extract exact spans."
    assert first.config_hash == second.config_hash
    assert first.metadata("extract")["prompt_hash"] == second.metadata("extract")["prompt_hash"]


def test_prompt_or_model_change_changes_provenance_hash(tmp_path) -> None:
    config, prompts = write_registry(tmp_path)
    original = ModelRegistry.load(config, prompts)

    (prompts / "extract" / "gemma-v1" / "v1" / "system.txt").write_text(
        "Select exact spans only.", encoding="utf-8"
    )
    changed_prompt = ModelRegistry.load(config, prompts)
    assert (
        changed_prompt.prompt_for("extract").prompt_hash
        != original.prompt_for("extract").prompt_hash
    )

    config, prompts = write_registry(tmp_path, prompt="Select exact spans only.", model="gemma-2")
    changed_model = ModelRegistry.load(config, prompts)
    assert changed_model.config_hash != changed_prompt.config_hash


def test_registry_rejects_missing_prompt_artifact(tmp_path) -> None:
    config, prompts = write_registry(tmp_path)
    (prompts / "extract" / "gemma-v1" / "v1" / "schema.json").unlink()
    with pytest.raises(ModelRegistryError, match="missing prompt artifact"):
        ModelRegistry.load(config, prompts)


def test_embedding_profile_requires_positive_dimensions(tmp_path) -> None:
    config = tmp_path / "models.yaml"
    config.write_text(
        """version: 1
profiles:
  bad:
    kind: embedding
    base_url: http://model:8000
    model: qwen
    dimensions: 0
tasks:
  embed:
    profile: bad
""",
        encoding="utf-8",
    )
    with pytest.raises(ModelRegistryError, match="positive dimensions"):
        ModelRegistry.load(config, tmp_path / "prompts")


def test_checked_in_registry_and_prompt_artifacts_load() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = ModelRegistry.load(root / "config/models.yaml", root / "config/prompts")

    assert registry.profile_for("extraction").kind == "chat"
    assert registry.profile_for("extraction").structured_output == "json_object"
    assert registry.profile_for("embed_evidence").dimensions == 1024
    assert registry.profile_for("embed_quality").dimensions == 2560
    assert registry.profile_for("embed_query").query_prefix.startswith("Instruct:")
    for task in ("extraction", "highlighting"):
        metadata = registry.metadata(task)
        assert metadata["prompt_version"] == "v1"
        assert len(metadata["prompt_hash"]) == 64
