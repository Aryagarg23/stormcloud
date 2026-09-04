from __future__ import annotations

import base64
import hashlib
import math
import smtplib
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .events import EventEnvelope, enqueue
from .evidence import (
    BundleMemberEvidence,
    EvidenceSpan,
    assemble_bundle_evidence,
    assemble_signal_evidence,
)
from .fetcher import FetcherClient, FetchFailure, FetchRequest
from .model_gateway import EmbeddingPurpose, ModelGatewayClient
from .models import (
    Bundle,
    BundleItem,
    Document,
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
    ProcessingStage,
    ProcessingStatus,
    ResearcherExtraction,
    Signal,
    StageStatus,
)
from .nlp import analyze_text
from .storage import ObjectStore

settings = get_settings()


def now() -> datetime:
    return datetime.now(UTC)


def _operation(session: Session, payload: dict[str, Any]) -> Operation | None:
    value = payload.get("operation_id")
    return session.get(Operation, uuid.UUID(value)) if value else None


def mark_stage(
    session: Session,
    payload: dict[str, Any],
    name: str,
    state: StageStatus,
    error: dict | None = None,
) -> None:
    operation = _operation(session, payload)
    if not operation:
        return
    stage = session.scalar(
        select(ProcessingStage)
        .where(ProcessingStage.operation_id == operation.id, ProcessingStage.name == name)
        .order_by(ProcessingStage.attempt.desc())
    )
    if not stage:
        stage = ProcessingStage(operation_id=operation.id, name=name, attempt=1)
        session.add(stage)
        session.flush()
    stage.status = state
    stage.error = error
    if state == StageStatus.running:
        stage.started_at = now()
        operation.status = OperationStatus.running
    if state in (StageStatus.succeeded, StageStatus.failed, StageStatus.dead_lettered):
        stage.completed_at = now()


def emit(
    session: Session,
    parent: EventEnvelope,
    subject: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    extra: dict | None = None,
) -> None:
    payload = {"operation_id": parent.payload.get("operation_id"), **(extra or {})}
    enqueue(
        session,
        EventEnvelope.create(
            subject,
            aggregate_type,
            aggregate_id,
            payload,
            correlation_id=parent.correlation_id,
            causation_id=parent.event_id,
        ),
    )


async def process_fetch(session: Session, event: EventEnvelope) -> None:
    signal = session.get(Signal, uuid.UUID(event.aggregate_id))
    if not signal:
        raise ValueError("signal not found")
    mark_stage(session, event.payload, "fetch", StageStatus.running)
    client = FetcherClient(
        settings.fetcher_base_url,
        timeout_seconds=settings.fetcher_timeout_seconds,
        token=settings.fetcher_token.get_secret_value(),
        max_response_bytes=max(settings.fetcher_max_bytes * 2, 32 * 1024 * 1024),
    )
    try:
        result = await client.fetch(
            FetchRequest(request_id=event.event_id, url=signal.submitted_url)
        )
    finally:
        await client.close()
    if isinstance(result, FetchFailure):
        raise RuntimeError(f"{result.code}: {result.message}")
    normalized = ObjectStore().put_bytes(
        settings.s3_bucket_normalized,
        "documents",
        result.normalized_text.encode(),
        "text/plain; charset=utf-8",
    )
    raw_key = None
    if result.raw_content_base64:
        raw = ObjectStore().put_bytes(
            settings.s3_bucket_raw,
            "fetches",
            base64.b64decode(result.raw_content_base64),
            result.raw_content_type or "application/octet-stream",
        )
        raw_key = raw.key
    document = session.scalar(
        select(Document).where(Document.canonical_url == result.canonical_url)
    )
    if not document:
        document = Document(canonical_url=result.canonical_url)
        session.add(document)
        session.flush()
    version = session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.content_sha256 == result.content_sha256,
        )
    )
    if not version:
        version = DocumentVersion(
            document_id=document.id,
            content_sha256=result.content_sha256,
            canonical_url=result.canonical_url,
            media_type=result.media_type,
            retrieved_at=result.retrieved_at,
            raw_object_key=raw_key,
            normalized_object_key=normalized.key,
            normalized_text_length=len(result.normalized_text),
            segments=[segment.model_dump(mode="json") for segment in result.segments],
            metadata_json=result.metadata,
        )
        session.add(version)
        session.flush()
        document.latest_version_id = version.id
    signal.document_version_id = version.id
    signal.status = ProcessingStatus.running
    mark_stage(session, event.payload, "fetch", StageStatus.succeeded)
    emit(
        session,
        event,
        "stormcloud.document.ready.v1",
        "signal",
        signal.id,
        {"document_version_id": str(version.id)},
    )


async def process_extraction(session: Session, event: EventEnvelope) -> None:
    signal = session.get(Signal, uuid.UUID(event.aggregate_id))
    if not signal:
        raise ValueError("signal not found")
    mark_stage(session, event.payload, "extraction", StageStatus.running)
    description = signal.description_verbatim or ""
    if description:
        client = ModelGatewayClient(settings.model_gateway_url)
        try:
            result = await client.structured("extraction", {"description_verbatim": description})
        finally:
            await client.close()
        digest = hashlib.sha256(description.encode()).hexdigest()
        existing = session.scalar(
            select(ResearcherExtraction).where(
                ResearcherExtraction.signal_id == signal.id,
                ResearcherExtraction.input_sha256 == digest,
                ResearcherExtraction.model_profile == result.metadata["profile"],
                ResearcherExtraction.prompt_hash == result.metadata["prompt_hash"],
            )
        )
        if not existing:
            ObjectStore().put_json(
                settings.s3_bucket_derived,
                "model/extraction",
                {"output": result.output, "metadata": result.metadata},
            )
            session.add(
                ResearcherExtraction(
                    signal_id=signal.id,
                    input_sha256=digest,
                    output=result.output,
                    model_profile=result.metadata["profile"],
                    prompt_hash=result.metadata["prompt_hash"],
                    config_hash=result.metadata["config_hash"],
                )
            )
    mark_stage(session, event.payload, "extraction", StageStatus.succeeded)
    emit(session, event, "stormcloud.researcher.ready.v1", "signal", signal.id)


async def process_nlp(session: Session, event: EventEnvelope) -> None:
    signal = session.get(Signal, uuid.UUID(event.aggregate_id))
    version = session.get(DocumentVersion, signal.document_version_id) if signal else None
    if not version:
        raise ValueError("document version not found")
    mark_stage(session, event.payload, "nlp", StageStatus.running)
    existing = session.scalar(
        select(NlpArtifact).where(
            NlpArtifact.document_version_id == version.id,
            NlpArtifact.recipe_version == "deterministic-nlp-v1",
        )
    )
    if not existing:
        text = (
            ObjectStore()
            .get_bytes(settings.s3_bucket_normalized, version.normalized_object_key)
            .decode()
        )
        result = analyze_text(text)
        stored = ObjectStore().put_json(
            settings.s3_bucket_derived, "nlp", result.model_dump(mode="json")
        )
        existing = NlpArtifact(
            document_version_id=version.id,
            recipe_version=result.recipe_version,
            object_key=stored.key,
            content_sha256=stored.sha256,
        )
        session.add(existing)
    mark_stage(session, event.payload, "nlp", StageStatus.succeeded)
    emit(
        session,
        event,
        "stormcloud.nlp.ready.v1",
        "signal",
        signal.id,
        {"document_version_id": str(version.id)},
    )


async def process_highlighting(session: Session, event: EventEnvelope) -> None:
    signal = session.get(Signal, uuid.UUID(event.aggregate_id))
    version = session.get(DocumentVersion, signal.document_version_id) if signal else None
    if not version:
        raise ValueError("document version not found")
    mark_stage(session, event.payload, "highlighting", StageStatus.running)
    sentences = [row for row in version.segments if row.get("kind") == "sentence"]
    client = ModelGatewayClient(settings.model_gateway_url)
    try:
        result = await client.structured(
            "highlighting",
            {
                "description_verbatim": signal.description_verbatim
                or "Select concrete factual evidence.",
                "segments": sentences,
            },
        )
    finally:
        await client.close()
    selected = set(result.output["sentence_ids"])
    for segment in sentences:
        if segment["id"] not in selected:
            continue
        existing = session.scalar(
            select(Highlight).where(
                Highlight.signal_id == signal.id,
                Highlight.document_version_id == version.id,
                Highlight.start_offset == segment["start"],
                Highlight.end_offset == segment["end"],
                Highlight.kind == HighlightKind.automatic,
            )
        )
        if not existing:
            session.add(
                Highlight(
                    signal_id=signal.id,
                    document_version_id=version.id,
                    kind=HighlightKind.automatic,
                    start_offset=segment["start"],
                    end_offset=segment["end"],
                    text_verbatim=segment["text"],
                    text_sha256=hashlib.sha256(segment["text"].encode()).hexdigest(),
                    score=1.0,
                    model_profile=result.metadata["profile"],
                    prompt_hash=result.metadata["prompt_hash"],
                )
            )
    ObjectStore().put_json(
        settings.s3_bucket_derived,
        "model/highlighting",
        {"output": result.output, "metadata": result.metadata},
    )
    mark_stage(session, event.payload, "highlighting", StageStatus.succeeded)
    emit(session, event, "stormcloud.highlights.ready.v1", "signal", signal.id)


def _stage_done(session: Session, operation_id: str | None, name: str) -> bool:
    if not operation_id:
        return False
    return (
        session.scalar(
            select(ProcessingStage.id).where(
                ProcessingStage.operation_id == uuid.UUID(operation_id),
                ProcessingStage.name == name,
                ProcessingStage.status == StageStatus.succeeded,
            )
        )
        is not None
    )


def build_signal_evidence(session: Session, event: EventEnvelope) -> None:
    signal = session.get(Signal, uuid.UUID(event.aggregate_id))
    if not signal or not signal.document_version_id:
        return
    if event.subject != "stormcloud.highlight.changed.v1":
        if not all(
            _stage_done(session, event.payload.get("operation_id"), stage)
            for stage in ("fetch", "extraction", "nlp", "highlighting")
        ):
            return
    version = session.get(DocumentVersion, signal.document_version_id)
    text = (
        ObjectStore()
        .get_bytes(settings.s3_bucket_normalized, version.normalized_object_key)
        .decode()
    )
    suppressed = set(
        session.scalars(
            select(HighlightSuppression.highlight_id).where(
                HighlightSuppression.signal_id == signal.id,
                HighlightSuppression.restored_at.is_(None),
            )
        )
    )
    human, automatic = [], []
    for item in session.scalars(select(Highlight).where(Highlight.signal_id == signal.id)):
        span = EvidenceSpan(
            id=str(item.id),
            source_id=f"document:{version.id}",
            source_kind="document",
            start=item.start_offset,
            end=item.end_offset,
            text=item.text_verbatim,
            origin="human" if item.kind == HighlightKind.human else "auto",
            tombstoned=item.tombstoned_at is not None,
            suppressed=item.id in suppressed,
        )
        (human if item.kind == HighlightKind.human else automatic).append(span)
    nlp = session.scalar(
        select(NlpArtifact)
        .where(NlpArtifact.document_version_id == version.id)
        .order_by(NlpArtifact.created_at.desc())
    )
    features = []
    if nlp:
        payload = ObjectStore().get_json(settings.s3_bucket_derived, nlp.object_key)
        for item in payload["features"][:100]:
            features.append(
                EvidenceSpan(
                    id=item["id"],
                    source_id=f"document:{version.id}",
                    source_kind="document",
                    start=item["start"],
                    end=item["end"],
                    text=item["text"],
                    origin="nlp",
                )
            )
    extraction = session.scalar(
        select(ResearcherExtraction)
        .where(ResearcherExtraction.signal_id == signal.id)
        .order_by(ResearcherExtraction.created_at.desc())
    )
    snapshot = assemble_signal_evidence(
        signal_id=str(signal.id),
        description_verbatim=signal.description_verbatim or "",
        document_id=str(version.id),
        document_text=text,
        human_highlights=human,
        auto_highlights=automatic,
        source_features=features,
        extraction=extraction.output if extraction else {},
        provenance={"document_version_id": str(version.id), "code_version": settings.code_version},
    )
    latest = (
        session.get(EvidenceVersion, signal.latest_evidence_id)
        if signal.latest_evidence_id
        else None
    )
    if latest and latest.content_sha256 == snapshot.content_sha256:
        signal.status = ProcessingStatus.ready
        operation = _operation(session, event.payload)
        if operation:
            operation.status = OperationStatus.succeeded
            operation.completed_at = now()
        return
    stored = ObjectStore().put_json(
        settings.s3_bucket_derived,
        "evidence/signals",
        {"evidence_text": snapshot.evidence_text, "manifest": snapshot.manifest},
    )
    revision = (
        session.scalar(
            select(func.max(EvidenceVersion.revision)).where(EvidenceVersion.signal_id == signal.id)
        )
        or 0
    ) + 1
    evidence = EvidenceVersion(
        signal_id=signal.id,
        revision=revision,
        object_key=stored.key,
        content_sha256=snapshot.content_sha256,
        manifest=snapshot.manifest,
        processing_run_id=_operation(session, event.payload).id
        if _operation(session, event.payload)
        else None,
        code_version=settings.code_version,
        recipe_version=snapshot.recipe_version,
        config_hash=hashlib.sha256(settings.code_version.encode()).hexdigest(),
    )
    session.add(evidence)
    session.flush()
    signal.latest_evidence_id = evidence.id
    emit(
        session,
        event,
        "stormcloud.signal.evidence.ready.v1",
        "signal",
        signal.id,
        {"evidence_version_id": str(evidence.id)},
    )


def build_ready_bundles(session: Session, event: EventEnvelope) -> None:
    if event.aggregate_type == "bundle":
        bundle = session.get(Bundle, uuid.UUID(event.aggregate_id))
        bundles = [bundle] if bundle and bundle.archived_at is None else []
    else:
        signal_id = uuid.UUID(event.aggregate_id)
        bundles = session.scalars(
            select(Bundle)
            .join(BundleItem)
            .where(BundleItem.signal_id == signal_id, Bundle.archived_at.is_(None))
        ).all()
    for bundle in bundles:
        bundle_operation = (
            _operation(session, event.payload)
            if event.aggregate_type == "bundle"
            else session.scalar(
                select(Operation)
                .where(
                    Operation.aggregate_type == "bundle",
                    Operation.aggregate_id == bundle.id,
                    Operation.status.in_((OperationStatus.pending, OperationStatus.running)),
                )
                .order_by(Operation.created_at.desc())
            )
        )
        items = session.scalars(
            select(BundleItem)
            .where(BundleItem.bundle_id == bundle.id)
            .order_by(BundleItem.position)
        ).all()
        if bundle_operation and bundle_operation.status == OperationStatus.pending:
            bundle_operation.status = OperationStatus.running
        if not items:
            continue
        if event.subject == "stormcloud.bundle.retry.requested.v1":
            missing = []
            for item in items:
                signal = session.get(Signal, item.signal_id)
                if signal and not signal.latest_evidence_id:
                    missing.append(signal)
            for signal in missing:
                child_operation = Operation(
                    aggregate_type="signal",
                    aggregate_id=signal.id,
                    kind="bundle_member_retry",
                    requested_by_id=(
                        bundle_operation.requested_by_id if bundle_operation else None
                    ),
                    status=OperationStatus.pending,
                )
                session.add(child_operation)
                session.flush()
                enqueue(
                    session,
                    EventEnvelope.create(
                        "stormcloud.signal.retry.requested.v1",
                        "signal",
                        signal.id,
                        {
                            "operation_id": str(child_operation.id),
                            "bundle_id": str(bundle.id),
                        },
                        correlation_id=event.correlation_id,
                        causation_id=event.event_id,
                    ),
                )
                signal.status = ProcessingStatus.pending
            if missing:
                continue
        members = []
        for item in items:
            signal = session.get(Signal, item.signal_id)
            if not signal or not signal.latest_evidence_id:
                members = []
                break
            evidence = session.get(EvidenceVersion, signal.latest_evidence_id)
            artifact = ObjectStore().get_json(settings.s3_bucket_derived, evidence.object_key)
            members.append(
                BundleMemberEvidence(
                    signal_id=str(signal.id),
                    evidence_version_id=str(evidence.id),
                    evidence_text=artifact["evidence_text"],
                    note=item.note,
                    position=item.position,
                )
            )
        if not members:
            continue
        snapshot = assemble_bundle_evidence(
            bundle_id=str(bundle.id),
            members=members,
            thesis=bundle.thesis,
            ordered=bundle.ordered,
            provenance={"code_version": settings.code_version},
        )
        latest = (
            session.get(EvidenceVersion, bundle.latest_evidence_id)
            if bundle.latest_evidence_id
            else None
        )
        if latest and latest.content_sha256 == snapshot.content_sha256:
            bundle.status = ProcessingStatus.ready
            if bundle_operation:
                bundle_operation.status = OperationStatus.succeeded
                bundle_operation.completed_at = now()
            continue
        stored = ObjectStore().put_json(
            settings.s3_bucket_derived,
            "evidence/bundles",
            {"evidence_text": snapshot.evidence_text, "manifest": snapshot.manifest},
        )
        revision = (
            session.scalar(
                select(func.max(EvidenceVersion.revision)).where(
                    EvidenceVersion.bundle_id == bundle.id
                )
            )
            or 0
        ) + 1
        evidence = EvidenceVersion(
            bundle_id=bundle.id,
            revision=revision,
            object_key=stored.key,
            content_sha256=snapshot.content_sha256,
            manifest=snapshot.manifest,
            processing_run_id=bundle_operation.id if bundle_operation else None,
            code_version=settings.code_version,
            recipe_version=snapshot.recipe_version,
            config_hash=hashlib.sha256(settings.code_version.encode()).hexdigest(),
        )
        session.add(evidence)
        session.flush()
        bundle.latest_evidence_id = evidence.id
        emit(
            session,
            event,
            "stormcloud.bundle.evidence.ready.v1",
            "bundle",
            bundle.id,
            {
                "operation_id": str(bundle_operation.id) if bundle_operation else None,
                "evidence_version_id": str(evidence.id),
            },
        )


async def process_embedding(session: Session, event: EventEnvelope) -> None:
    evidence = session.get(EvidenceVersion, uuid.UUID(event.payload["evidence_version_id"]))
    if not evidence:
        raise ValueError("evidence not found")
    artifact = ObjectStore().get_json(settings.s3_bucket_derived, evidence.object_key)
    aggregate_type = event.aggregate_type
    task = "embed_bundle" if aggregate_type == "bundle" else "embed_evidence"
    purpose = EmbeddingPurpose.BUNDLE if aggregate_type == "bundle" else EmbeddingPurpose.EVIDENCE
    client = ModelGatewayClient(settings.model_gateway_url)
    try:
        result = await client.embed(task, [artifact["evidence_text"]], purpose)
    finally:
        await client.close()
    aggregate_id = evidence.bundle_id or evidence.signal_id
    input_hash = hashlib.sha256(artifact["evidence_text"].encode()).hexdigest()
    existing = session.scalar(
        select(Embedding).where(
            Embedding.subject_type == aggregate_type,
            Embedding.subject_id == aggregate_id,
            Embedding.kind == "evidence",
            Embedding.model_profile == result.metadata["profile"],
            Embedding.input_sha256 == input_hash,
        )
    )
    if not existing:
        existing = Embedding(
            subject_type=aggregate_type,
            subject_id=aggregate_id,
            kind="evidence",
            model_profile=result.metadata["profile"],
            dimension=result.metadata["dimensions"],
            vector=result.embeddings[0],
            input_sha256=input_hash,
            config_hash=result.metadata["config_hash"],
        )
        session.add(existing)
        session.flush()
    emit(
        session,
        event,
        f"stormcloud.{aggregate_type}.embedding.ready.v1",
        aggregate_type,
        aggregate_id,
        {"embedding_id": str(existing.id), "evidence_version_id": str(evidence.id)},
    )


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return numerator / denominator if denominator else 0


def process_graph(session: Session, event: EventEnvelope) -> None:
    embedding = session.get(Embedding, uuid.UUID(event.payload["embedding_id"]))
    if not embedding:
        raise ValueError("embedding not found")
    peers = session.scalars(
        select(Embedding).where(
            Embedding.subject_type == embedding.subject_type,
            Embedding.kind == embedding.kind,
            Embedding.model_profile == embedding.model_profile,
            Embedding.id != embedding.id,
        )
    ).all()
    scored = sorted(
        ((_cosine(list(embedding.vector), list(peer.vector)), peer) for peer in peers),
        key=lambda row: row[0],
        reverse=True,
    )
    evidence = session.get(EvidenceVersion, uuid.UUID(event.payload["evidence_version_id"]))
    revision = evidence.revision if evidence else 1
    for score, peer in scored[: settings.similarity_top_k]:
        if score < settings.similarity_threshold:
            continue
        for source, target in (
            (embedding.subject_id, peer.subject_id),
            (peer.subject_id, embedding.subject_id),
        ):
            exists = session.scalar(
                select(Edge).where(
                    Edge.source_type == embedding.subject_type,
                    Edge.source_id == source,
                    Edge.target_type == embedding.subject_type,
                    Edge.target_id == target,
                    Edge.kind == EdgeKind.similarity,
                    Edge.revision == revision,
                )
            )
            if not exists:
                session.add(
                    Edge(
                        source_type=embedding.subject_type,
                        source_id=source,
                        target_type=embedding.subject_type,
                        target_id=target,
                        kind=EdgeKind.similarity,
                        weight=score,
                        revision=revision,
                        model_profile=embedding.model_profile,
                        evidence_version_id=evidence.id if evidence else None,
                    )
                )
    aggregate = session.get(
        Signal if embedding.subject_type == "signal" else Bundle, embedding.subject_id
    )
    if aggregate:
        aggregate.status = ProcessingStatus.ready
    operation = _operation(session, event.payload)
    if operation:
        operation.status = OperationStatus.succeeded
        operation.completed_at = now()


def send_invitation(event: EventEnvelope) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = event.payload["email"]
    message["Subject"] = "You are invited to Stormcloud"
    message.set_content(f"Accept your Stormcloud invitation:\n\n{event.payload['invite_url']}\n")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(message)
