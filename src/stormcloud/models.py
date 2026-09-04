from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class Role(str, enum.Enum):
    admin = "admin"
    member = "member"


class ProcessingStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    ready = "ready"
    failed = "failed"
    archived = "archived"


class OperationStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class StageStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    dead_lettered = "dead_lettered"


class HighlightKind(str, enum.Enum):
    human = "human"
    automatic = "automatic"


class ArticleGradeValue(enum.IntEnum):
    tier_1 = 1
    tier_2 = 2
    tier_3 = 3
    tier_4 = 4


class EdgeKind(str, enum.Enum):
    next = "NEXT"
    similarity = "SIMILARITY"


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Timestamps, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"), default=Role.member)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Invitation(Timestamps, Base):
    __tablename__ = "invitations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[Role] = mapped_column(Enum(Role, name="invite_role"), default=Role.member)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class RefreshSession(Timestamps, Base):
    __tablename__ = "refresh_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("refresh_sessions.id"))


class Signal(Timestamps, Base):
    __tablename__ = "signals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    submitted_url: Mapped[str] = mapped_column(Text)
    description_verbatim: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id")
    )
    status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, name="processing_status"),
        default=ProcessingStatus.pending,
        index=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_versions.id", name="fk_signal_latest_evidence", use_alter=True)
    )


class SignalComment(Timestamps, Base):
    """A team-shared comment on a signal."""

    __tablename__ = "signal_comments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    author: Mapped[User] = relationship()


class ArticleGrade(Timestamps, Base):
    """Current team-wide grade for a signal."""

    __tablename__ = "article_grades"
    __table_args__ = (
        CheckConstraint("grade IS NULL OR grade BETWEEN 1 AND 4", name="ck_article_grade_range"),
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), primary_key=True
    )
    grade: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    graded_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    signal: Mapped[Signal] = relationship()
    graded_by: Mapped[User] = relationship()


class ArticleGradeEvent(Timestamps, Base):
    """Immutable audit event for a shared grade change."""

    __tablename__ = "article_grade_events"
    __table_args__ = (
        CheckConstraint(
            "grade IS NULL OR grade BETWEEN 1 AND 4",
            name="ck_article_grade_event_range",
        ),
        UniqueConstraint("signal_id", "revision"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), index=True
    )
    grade: Mapped[int | None] = mapped_column(Integer)
    previous_grade: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    changed_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class Bundle(Timestamps, Base):
    __tablename__ = "bundles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    thesis: Mapped[str | None] = mapped_column(Text)
    ordered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, name="bundle_status"), default=ProcessingStatus.pending
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_versions.id", name="fk_bundle_latest_evidence", use_alter=True)
    )
    items: Mapped[list[BundleItem]] = relationship(
        back_populates="bundle", cascade="all, delete-orphan", order_by="BundleItem.position"
    )


class BundleItem(Timestamps, Base):
    __tablename__ = "bundle_items"
    __table_args__ = (
        UniqueConstraint("bundle_id", "position"),
        UniqueConstraint("bundle_id", "signal_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    bundle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bundles.id", ondelete="CASCADE"), index=True
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    bundle: Mapped[Bundle] = relationship(back_populates="items")
    signal: Mapped[Signal] = relationship()


class Document(Timestamps, Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True)
    latest_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", name="fk_document_latest_version", use_alter=True)
    )


class DocumentVersion(Timestamps, Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "content_sha256"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    canonical_url: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(255))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_object_key: Mapped[str | None] = mapped_column(Text)
    normalized_object_key: Mapped[str] = mapped_column(Text)
    normalized_text_length: Mapped[int] = mapped_column(Integer)
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class ResearcherExtraction(Timestamps, Base):
    __tablename__ = "researcher_extractions"
    __table_args__ = (
        UniqueConstraint("signal_id", "input_sha256", "model_profile", "prompt_hash"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), index=True
    )
    input_sha256: Mapped[str] = mapped_column(String(64))
    output: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model_profile: Mapped[str] = mapped_column(String(128))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    config_hash: Mapped[str] = mapped_column(String(64))


class NlpArtifact(Timestamps, Base):
    __tablename__ = "nlp_artifacts"
    __table_args__ = (UniqueConstraint("document_version_id", "recipe_version"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    recipe_version: Mapped[str] = mapped_column(String(128))
    object_key: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))


class Highlight(Timestamps, Base):
    __tablename__ = "highlights"
    __table_args__ = (
        UniqueConstraint("signal_id", "document_version_id", "start_offset", "end_offset", "kind"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), index=True
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"))
    kind: Mapped[HighlightKind] = mapped_column(Enum(HighlightKind, name="highlight_kind"))
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    text_sha256: Mapped[str] = mapped_column(String(64))
    text_verbatim: Mapped[str] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    model_profile: Mapped[str | None] = mapped_column(String(128))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HighlightSuppression(Timestamps, Base):
    __tablename__ = "highlight_suppressions"
    __table_args__ = (UniqueConstraint("signal_id", "highlight_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"))
    highlight_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("highlights.id", ondelete="CASCADE"))
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvidenceVersion(Timestamps, Base):
    __tablename__ = "evidence_versions"
    __table_args__ = (
        CheckConstraint("num_nonnulls(signal_id, bundle_id) = 1", name="ck_evidence_one_owner"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), index=True
    )
    bundle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bundles.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    object_key: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    processing_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("operations.id"))
    code_version: Mapped[str] = mapped_column(String(128))
    recipe_version: Mapped[str] = mapped_column(String(128))
    model_profile: Mapped[str | None] = mapped_column(String(128))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    config_hash: Mapped[str] = mapped_column(String(64))


class Embedding(Timestamps, Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint("subject_type", "subject_id", "kind", "model_profile", "input_sha256"),
        Index("ix_embedding_subject", "subject_type", "subject_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(32))
    model_profile: Mapped[str] = mapped_column(String(128))
    dimension: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list[float]] = mapped_column(Vector())
    input_sha256: Mapped[str] = mapped_column(String(64))
    config_hash: Mapped[str] = mapped_column(String(64))


class Edge(Timestamps, Base):
    __tablename__ = "edges"
    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_id", "target_type", "target_id", "kind", "revision"
        ),
        Index("ix_edges_source", "source_type", "source_id", "kind"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[EdgeKind] = mapped_column(Enum(EdgeKind, name="edge_kind"))
    weight: Mapped[float | None] = mapped_column(Float)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    model_profile: Mapped[str | None] = mapped_column(String(128))
    evidence_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_versions.id")
    )


class Operation(Timestamps, Base):
    __tablename__ = "operations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    aggregate_type: Mapped[str] = mapped_column(String(32), index=True)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[OperationStatus] = mapped_column(
        Enum(OperationStatus, name="operation_status"), default=OperationStatus.pending
    )
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stages: Mapped[list[ProcessingStage]] = relationship(
        cascade="all, delete-orphan", order_by="ProcessingStage.created_at"
    )


class ProcessingStage(Timestamps, Base):
    __tablename__ = "processing_stages"
    __table_args__ = (UniqueConstraint("operation_id", "name", "attempt"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[StageStatus] = mapped_column(
        Enum(StageStatus, name="stage_status"), default=StageStatus.pending
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Timestamps, Base):
    __tablename__ = "outbox_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, default=new_id)
    subject: Mapped[str] = mapped_column(String(255), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    aggregate_type: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    causation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class InboxEvent(Timestamps, Base):
    __tablename__ = "inbox_events"
    __table_args__ = (UniqueConstraint("consumer", "event_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    consumer: Mapped[str] = mapped_column(String(128))
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IdempotencyRecord(Timestamps, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB)


Index(
    "uq_evidence_signal_revision",
    EvidenceVersion.signal_id,
    EvidenceVersion.revision,
    unique=True,
    postgresql_where=sql_text("signal_id IS NOT NULL"),
)
Index(
    "uq_evidence_bundle_revision",
    EvidenceVersion.bundle_id,
    EvidenceVersion.revision,
    unique=True,
    postgresql_where=sql_text("bundle_id IS NOT NULL"),
)
