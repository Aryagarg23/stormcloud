from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from stormcloud import signal_detail as signal_detail_module
from stormcloud.config import get_settings
from stormcloud.db import get_db
from stormcloud.main import app
from stormcloud.models import (
    DocumentVersion,
    Edge,
    EdgeKind,
    Embedding,
    EvidenceVersion,
    Highlight,
    HighlightKind,
    HighlightSuppression,
    NlpArtifact,
    Operation,
    OperationStatus,
    ProcessingStatus,
    ResearcherExtraction,
    Role,
    Signal,
    SignalComment,
    StageStatus,
)
from stormcloud.security import current_user
from stormcloud.signal_detail import build_signal_detail

NOW = datetime(2026, 9, 4, tzinfo=UTC)


class FakeStore:
    def __init__(self, *, text: str = "", json_by_key: dict | None = None):
        self.text = text
        self.json_by_key = json_by_key or {}

    def get_bytes(self, bucket: str, key: str) -> bytes:
        return self.text.encode()

    def get_json(self, bucket: str, key: str):
        return self.json_by_key[key]


class FakeSession:
    def __init__(self, *, gets: dict | None = None, scalars: dict | None = None, scalar=None):
        self.gets = gets or {}
        self.scalar_rows = scalars or {}
        self.scalar_values = scalar or {}

    @staticmethod
    def _entity(statement):
        return statement.column_descriptions[0].get("entity")

    def get(self, model, row_id):
        return self.gets.get((model, row_id))

    def scalar(self, statement):
        return self.scalar_values.get(self._entity(statement))

    def scalars(self, statement):
        return list(self.scalar_rows.get(self._entity(statement), []))


def row(**values):
    return SimpleNamespace(**values)


def test_build_signal_detail_maps_all_public_artifacts_without_secrets() -> None:
    signal_id, document_id, document_version_id = uuid4(), uuid4(), uuid4()
    target_id, target_document_id, target_version_id = uuid4(), uuid4(), uuid4()
    human_id, auto_id = uuid4(), uuid4()
    signal = row(
        id=signal_id,
        submitted_url="https://example.test/source",
        description_verbatim="A researcher observation",
        created_by_id=uuid4(),
        document_version_id=document_version_id,
        status=ProcessingStatus.failed,
        archived_at=None,
        latest_evidence_id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
    )
    document = row(
        id=document_version_id,
        document_id=document_id,
        canonical_url="https://example.test/article",
        media_type="text/plain",
        retrieved_at=NOW,
        normalized_object_key="normalized",
        content_sha256="a" * 64,
        metadata_json={
            "title": "Source title",
            "author": "Ada",
            "authorization": "Bearer must-not-leak",
            "nested": {"access_token": "must-not-leak", "public": "kept"},
        },
    )
    extraction_output = {
        "claims": [
            {
                "text": "researcher observation",
                "start": 2,
                "end": 24,
                "source_field": "description_verbatim",
                "kind": "claim",
            }
        ],
        "numbers": [],
        "dates": [],
    }
    extraction = row(
        id=uuid4(),
        output=extraction_output,
        model_profile="gemma",
        prompt_hash="b" * 64,
        config_hash="c" * 64,
        created_at=NOW,
    )
    nlp = row(
        id=uuid4(),
        recipe_version="deterministic-nlp-v1",
        object_key="nlp",
        content_sha256="d" * 64,
        created_at=NOW,
    )
    human = row(
        id=human_id,
        kind=HighlightKind.human,
        start_offset=0,
        end_offset=6,
        text_verbatim="Public",
        tombstoned_at=NOW,
        created_at=NOW,
    )
    automatic = row(
        id=auto_id,
        kind=HighlightKind.automatic,
        start_offset=7,
        end_offset=14,
        text_verbatim="article",
        tombstoned_at=None,
        created_at=NOW,
    )
    comment = row(
        id=uuid4(),
        signal_id=signal_id,
        body="Team note",
        author=row(id=uuid4(), email="member@example.com"),
        created_at=NOW,
    )
    evidence = row(
        id=signal.latest_evidence_id,
        revision=3,
        recipe_version="signal-evidence-v1",
        code_version="release",
        model_profile="gemma",
        prompt_hash="e" * 64,
        config_hash="f" * 64,
        object_key="evidence",
        manifest={"active_spans": []},
        created_at=NOW,
    )
    embedding = row(
        id=uuid4(),
        kind="evidence",
        model_profile="qwen",
        dimension=1024,
        config_hash="1" * 64,
        vector=[0.1, 0.2],
        input_sha256="2" * 64,
        created_at=NOW,
    )
    target = row(
        id=target_id,
        submitted_url="https://example.test/related",
        description_verbatim="Related signal text",
        document_version_id=target_version_id,
    )
    target_document = row(
        id=target_version_id,
        document_id=target_document_id,
        metadata_json={"title": "Related source"},
    )
    edge = row(
        id=uuid4(),
        target_id=target_id,
        weight=0.91,
        kind=EdgeKind.similarity,
        model_profile="qwen",
        revision=3,
    )
    stage = row(
        id=uuid4(),
        name="fetch",
        status=StageStatus.dead_lettered,
        attempt=2,
        error={"message": "upstream unavailable", "api_key": "must-not-leak"},
        created_at=NOW,
        started_at=NOW,
        completed_at=NOW,
        next_retry_at=None,
    )
    operation = row(
        id=uuid4(),
        status=OperationStatus.failed,
        error={"message": "upstream unavailable"},
        stages=[stage],
        created_at=NOW,
    )
    store = FakeStore(
        text="Public article text.",
        json_by_key={
            "nlp": {
                "segments": [{"kind": "sentence", "text": "Public article text."}],
                "features": [
                    {"id": "e1", "kind": "entity", "start": 0, "end": 6, "text": "Public"},
                    {"id": "n1", "kind": "number", "start": 15, "end": 16, "text": "1"},
                    {"id": "p1", "kind": "noun_phrase", "start": 0, "end": 14, "text": "Public article"},
                ],
                "secret": "must-not-leak",
            },
            "evidence": {
                "evidence_text": "Evidence text",
                "manifest": {"active_spans": [{"id": str(auto_id)}]},
            },
        },
    )
    db = FakeSession(
        gets={(DocumentVersion, document_version_id): document},
        scalar={
            ResearcherExtraction: extraction,
            NlpArtifact: nlp,
            Operation: operation,
        },
        scalars={
            Highlight: [human, automatic],
            HighlightSuppression: [auto_id],
            SignalComment: [comment],
            EvidenceVersion: [evidence],
            Embedding: [embedding],
            Edge: [edge],
            Signal: [target],
            DocumentVersion: [target_document],
        },
    )

    detail = build_signal_detail(db, signal, object_store=store)
    payload = detail.model_dump(mode="json")

    assert payload["document_id"] == str(document_id)
    assert payload["document_version"]["title"] == "Source title"
    assert payload["document_version"]["normalized_text"] == "Public article text."
    assert payload["document_version"]["metadata"] == {
        "title": "Source title",
        "author": "Ada",
        "nested": {"public": "kept"},
    }
    assert payload["researcher_extraction"]["claims"] == extraction_output["claims"]
    assert payload["nlp_artifact"]["sentence_count"] == 1
    assert payload["nlp_artifact"]["entities"][0]["start_offset"] == 0
    assert payload["nlp_artifact"]["noun_phrases"] == ["Public article"]
    assert payload["highlights"][0]["active"] is False
    assert payload["highlights"][1]["kind"] == "auto"
    assert payload["highlights"][1]["suppressed"] is True
    assert payload["comments"][0]["author"]["email"] == "member@example.com"
    assert payload["evidence_snapshots"][0]["evidence_text"] == "Evidence text"
    assert payload["evidence_snapshots"][0]["input_highlight_ids"] == [str(auto_id)]
    assert payload["embeddings"][0]["dimensions"] == 1024
    assert "vector" not in payload["embeddings"][0]
    assert payload["neighbors"][0]["title"] == "Related source"
    assert payload["neighbors"][0]["signal_text"] == "Related signal text"
    assert payload["stage_attempts"][0]["stage"] == "fetch"
    assert payload["failure"] == {
        "stage": "fetch",
        "detail": "upstream unavailable",
        "retryable": True,
    }
    assert "must-not-leak" not in str(payload)


def test_signal_detail_http_is_team_shared_and_sparse_safe(monkeypatch) -> None:
    signal_id = uuid4()
    owner_id = uuid4()
    member = row(
        id=uuid4(),
        email="teammate@example.com",
        role=Role.member,
        is_active=True,
        created_at=NOW,
    )
    signal = row(
        id=signal_id,
        submitted_url="https://example.test/pending",
        description_verbatim="Owned by another teammate",
        created_by_id=owner_id,
        document_version_id=None,
        status=ProcessingStatus.pending,
        archived_at=None,
        latest_evidence_id=None,
        created_at=NOW,
        updated_at=NOW,
    )
    db = FakeSession(gets={(Signal, signal_id): signal})
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: member
    monkeypatch.setattr(signal_detail_module, "ObjectStore", FakeStore)
    try:
        response = TestClient(app).get(
            f"/v1/signals/{signal_id}",
            headers={"host": get_settings().allowed_host_list[0]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(signal_id)
    assert payload["description_verbatim"] == "Owned by another teammate"
    assert payload["document_version"] is None
    assert payload["researcher_extraction"] is None
    assert payload["nlp_artifact"] is None
    assert payload["highlights"] == []
    assert payload["comments"] == []
    assert payload["evidence_snapshots"] == []
    assert payload["embeddings"] == []
    assert payload["neighbors"] == []
    assert payload["stage_attempts"] == []
    assert payload["failure"] is None
