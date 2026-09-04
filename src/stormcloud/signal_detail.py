from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .models import (
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
    ProcessingStatus,
    ResearcherExtraction,
    Signal,
    SignalComment,
    StageStatus,
)
from .schemas import SignalDetail
from .storage import ObjectStore

_SENSITIVE_METADATA_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
)


def _public_artifact_value(value, key: str = ""):
    """Remove credential-shaped metadata keys before returning stored artifacts."""
    if any(part in key.lower() for part in _SENSITIVE_METADATA_PARTS):
        return None
    if isinstance(value, dict):
        return {
            item_key: public_value
            for item_key, item_value in value.items()
            if (public_value := _public_artifact_value(item_value, str(item_key))) is not None
        }
    if isinstance(value, list):
        return [
            public_value
            for item in value
            if (public_value := _public_artifact_value(item)) is not None
        ]
    return value


def _error_text(error: dict | None) -> str | None:
    if not error:
        return None
    for key in ("message", "detail", "error"):
        value = error.get(key)
        if isinstance(value, str) and value:
            return value
    return json.dumps(error, sort_keys=True, ensure_ascii=False)


def _nlp_feature(feature: dict) -> dict:
    result = dict(feature)
    if "start" in feature:
        result["start_offset"] = feature["start"]
    if "end" in feature:
        result["end_offset"] = feature["end"]
    return result


def build_signal_detail(
    db: Session, signal: Signal, *, object_store: ObjectStore | None = None
) -> SignalDetail:
    """Build the team-shared, public projection of one signal and its artifacts."""
    store = object_store or ObjectStore()
    document = (
        db.get(DocumentVersion, signal.document_version_id)
        if signal.document_version_id
        else None
    )
    document_detail = None
    metadata: dict = {}
    if document:
        metadata = _public_artifact_value(document.metadata_json) or {}
        normalized_text = store.get_bytes(
            get_settings().s3_bucket_normalized, document.normalized_object_key
        ).decode("utf-8")
        title_value = metadata.get("title")
        title = title_value.strip() if isinstance(title_value, str) and title_value.strip() else None
        document_detail = {
            "id": document.id,
            "document_id": document.document_id,
            "canonical_url": document.canonical_url,
            "title": title,
            "media_type": document.media_type,
            "content_hash": document.content_sha256,
            "normalized_text": normalized_text,
            "retrieved_at": document.retrieved_at,
            "metadata": metadata,
        }
    else:
        title = None

    extraction = db.scalar(
        select(ResearcherExtraction)
        .where(ResearcherExtraction.signal_id == signal.id)
        .order_by(ResearcherExtraction.created_at.desc(), ResearcherExtraction.id.desc())
        .limit(1)
    )
    extraction_detail = None
    if extraction:
        output = _public_artifact_value(extraction.output) or {}
        extraction_detail = {
            "id": extraction.id,
            "claims": output.get("claims") or [],
            "numbers": output.get("numbers") or [],
            "dates": output.get("dates") or [],
            "model_profile": extraction.model_profile,
            "prompt_hash": extraction.prompt_hash,
            "config_hash": extraction.config_hash,
            "created_at": extraction.created_at,
        }

    nlp = None
    if document:
        nlp = db.scalar(
            select(NlpArtifact)
            .where(NlpArtifact.document_version_id == document.id)
            .order_by(NlpArtifact.created_at.desc(), NlpArtifact.id.desc())
            .limit(1)
        )
    nlp_detail = None
    if nlp:
        nlp_payload = _public_artifact_value(
            store.get_json(get_settings().s3_bucket_derived, nlp.object_key)
        ) or {}
        features = [
            _nlp_feature(item)
            for item in nlp_payload.get("features", [])
            if isinstance(item, dict)
        ]
        segments = nlp_payload.get("segments", [])
        nlp_detail = {
            "id": nlp.id,
            "recipe_version": nlp.recipe_version,
            "content_hash": nlp.content_sha256,
            "entities": [item for item in features if item.get("kind") == "entity"],
            "dates": [item for item in features if item.get("kind") == "date"],
            "numbers": [item for item in features if item.get("kind") == "number"],
            "noun_phrases": [
                item["text"]
                for item in features
                if item.get("kind") == "noun_phrase" and isinstance(item.get("text"), str)
            ],
            "sentence_count": sum(
                1
                for item in segments
                if isinstance(item, dict) and item.get("kind") == "sentence"
            ),
            "payload": nlp_payload,
            "created_at": nlp.created_at,
        }

    highlights = list(
        db.scalars(
            select(Highlight)
            .where(Highlight.signal_id == signal.id)
            .order_by(Highlight.created_at, Highlight.id)
        )
    )
    suppressed_ids = set(
        db.scalars(
            select(HighlightSuppression.highlight_id).where(
                HighlightSuppression.signal_id == signal.id,
                HighlightSuppression.restored_at.is_(None),
            )
        )
    )
    highlight_details = [
        {
            "id": item.id,
            "kind": "auto" if item.kind == HighlightKind.automatic else "human",
            "start_offset": item.start_offset,
            "end_offset": item.end_offset,
            "text": item.text_verbatim,
            "active": item.tombstoned_at is None,
            "suppressed": item.id in suppressed_ids,
            "rationale": None,
            "created_at": item.created_at,
        }
        for item in highlights
    ]

    comments = list(
        db.scalars(
            select(SignalComment)
            .where(SignalComment.signal_id == signal.id)
            .options(selectinload(SignalComment.author))
            .order_by(SignalComment.created_at, SignalComment.id)
        )
    )

    evidence_rows = list(
        db.scalars(
            select(EvidenceVersion)
            .where(EvidenceVersion.signal_id == signal.id)
            .order_by(EvidenceVersion.revision, EvidenceVersion.id)
        )
    )
    evidence_details = []
    for evidence in evidence_rows:
        artifact = _public_artifact_value(
            store.get_json(get_settings().s3_bucket_derived, evidence.object_key)
        ) or {}
        manifest = artifact.get("manifest")
        if not isinstance(manifest, dict):
            manifest = _public_artifact_value(evidence.manifest) or {}
        active_spans = manifest.get("active_spans", [])
        evidence_details.append(
            {
                "id": evidence.id,
                "revision": evidence.revision,
                "recipe_version": evidence.recipe_version,
                "code_version": evidence.code_version,
                "model_profile": evidence.model_profile,
                "prompt_hash": evidence.prompt_hash,
                "config_hash": evidence.config_hash,
                "input_highlight_ids": [
                    str(item["id"])
                    for item in active_spans
                    if isinstance(item, dict) and item.get("id") is not None
                ],
                "evidence_text": str(artifact.get("evidence_text") or ""),
                "manifest": manifest,
                "created_at": evidence.created_at,
            }
        )

    embedding_rows = list(
        db.scalars(
            select(Embedding)
            .where(Embedding.subject_type == "signal", Embedding.subject_id == signal.id)
            .order_by(Embedding.created_at, Embedding.id)
        )
    )
    embedding_details = [
        {
            "id": item.id,
            "kind": item.kind,
            "model_profile": item.model_profile,
            "dimensions": item.dimension,
            "config_hash": item.config_hash,
            "created_at": item.created_at,
        }
        for item in embedding_rows
    ]

    edge_rows = list(
        db.scalars(
            select(Edge)
            .where(
                Edge.source_type == "signal",
                Edge.source_id == signal.id,
                Edge.kind == EdgeKind.similarity,
            )
            .order_by(Edge.weight.desc(), Edge.id)
            .limit(100)
        )
    )
    target_ids = {edge.target_id for edge in edge_rows}
    target_rows = (
        list(db.scalars(select(Signal).where(Signal.id.in_(target_ids))))
        if target_ids
        else []
    )
    targets_by_id = {target.id: target for target in target_rows}
    target_document_ids = {
        target.document_version_id for target in target_rows if target.document_version_id
    }
    target_documents = (
        list(
            db.scalars(
                select(DocumentVersion).where(DocumentVersion.id.in_(target_document_ids))
            )
        )
        if target_document_ids
        else []
    )
    target_documents_by_id = {document.id: document for document in target_documents}

    neighbor_details = []
    for edge in edge_rows:
        target = targets_by_id.get(edge.target_id)
        if not target:
            continue
        target_document = target_documents_by_id.get(target.document_version_id)
        target_metadata = (
            _public_artifact_value(target_document.metadata_json) or {}
            if target_document
            else {}
        )
        target_title = target_metadata.get("title")
        if not isinstance(target_title, str) or not target_title.strip():
            target_title = target.description_verbatim or target.submitted_url
        neighbor_details.append(
            {
                "id": edge.id,
                "signal_id": signal.id,
                "target_signal_id": target.id,
                "target_id": target.id,
                "title": target_title,
                "signal_text": target.description_verbatim,
                "score": edge.weight or 0.0,
                "edge_type": edge.kind.value,
                "model_profile": edge.model_profile,
                "revision": edge.revision,
            }
        )

    operation = db.scalar(
        select(Operation)
        .where(Operation.aggregate_type == "signal", Operation.aggregate_id == signal.id)
        .options(selectinload(Operation.stages))
        .order_by(Operation.created_at.desc(), Operation.id.desc())
        .limit(1)
    )
    stages = list(operation.stages) if operation else []
    stage_details = []
    for stage in stages:
        error_detail = _public_artifact_value(stage.error) if stage.error else None
        status_value = stage.status.value
        stage_details.append(
            {
                "id": stage.id,
                "stage": stage.name,
                "status": status_value,
                "attempt": stage.attempt,
                "error": _error_text(error_detail),
                "error_detail": error_detail,
                "retryable": status_value in {"failed", "dead_lettered"},
                "created_at": stage.created_at,
                "started_at": stage.started_at,
                "completed_at": stage.completed_at,
                "next_retry_at": stage.next_retry_at,
            }
        )

    failure = None
    if signal.status == ProcessingStatus.failed:
        failed_stage = next(
            (
                stage
                for stage in reversed(stages)
                if stage.status in (StageStatus.failed, StageStatus.dead_lettered)
            ),
            None,
        )
        error_detail = (
            _public_artifact_value(failed_stage.error)
            if failed_stage and failed_stage.error
            else _public_artifact_value(operation.error)
            if operation and operation.error
            else None
        )
        failure = {
            "stage": failed_stage.name if failed_stage else None,
            "detail": _error_text(error_detail) or "Processing failed",
            "retryable": (
                bool(error_detail.get("retryable", True))
                if isinstance(error_detail, dict)
                else True
            ),
        }

    return SignalDetail.model_validate(
        {
            "id": signal.id,
            "submitted_url": signal.submitted_url,
            "description_verbatim": signal.description_verbatim,
            "status": signal.status,
            "document_version_id": signal.document_version_id,
            "latest_evidence_id": signal.latest_evidence_id,
            "archived_at": signal.archived_at,
            "created_at": signal.created_at,
            "updated_at": signal.updated_at,
            "canonical_url": document.canonical_url if document else None,
            "title": title,
            "document_id": document.document_id if document else None,
            "document_version": document_detail,
            "researcher_extraction": extraction_detail,
            "nlp_artifact": nlp_detail,
            "highlights": highlight_details,
            "comments": comments,
            "evidence_snapshots": evidence_details,
            "embeddings": embedding_details,
            "neighbors": neighbor_details,
            "operation_id": operation.id if operation else None,
            "stage_attempts": stage_details,
            "failure": failure,
        }
    )
