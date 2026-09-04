from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, model_validator

from .models import EdgeKind, HighlightKind, OperationStatus, ProcessingStatus, Role, StageStatus


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class InviteAccept(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=256)


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Role = Role.member


class InvitationView(ORM):
    id: UUID
    email: EmailStr
    role: Role
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class InvitationIssued(InvitationView):
    invite_url: str
    token: str | None = None


class UserView(ORM):
    id: UUID
    email: EmailStr
    role: Role
    is_active: bool
    created_at: datetime


class UserPatch(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class ArticleGradeActor(BaseModel):
    id: UUID
    email: EmailStr


class ArticleGradeCard(BaseModel):
    id: UUID
    url: str
    canonical_url: str | None = None
    title: str
    thumbnail_url: str | None = None
    grade: int | None = Field(default=None, ge=1, le=4)
    graded_by: ArticleGradeActor | None = None
    updated_by: ArticleGradeActor | None = None
    updated_at: datetime
    revision: str


class GradingBoard(BaseModel):
    ungraded: list[ArticleGradeCard] = Field(default_factory=list)
    tiers: dict[str, list[ArticleGradeCard]] = Field(default_factory=dict)
    revision: str


class GradeArticleInput(BaseModel):
    grade: int | None = Field(default=None, ge=1, le=4)
    expected_revision: str | None = None

    @model_validator(mode="after")
    def valid_revision(self):
        if self.expected_revision is not None:
            if not self.expected_revision.isdigit():
                raise ValueError("expected_revision must be a non-negative integer string")
        return self


class SignalCreate(BaseModel):
    url: HttpUrl
    description_verbatim: str = Field(min_length=1, max_length=100000)


class SignalView(ORM):
    id: UUID
    url: str = Field(validation_alias="submitted_url")
    description_verbatim: str | None
    status: ProcessingStatus
    document_version_id: UUID | None
    latest_evidence_id: UUID | None
    archived_at: datetime | None
    created_at: datetime


class BundleItemCreate(BaseModel):
    url: HttpUrl
    description_verbatim: str | None = Field(default=None, max_length=100000)
    note: str | None = Field(default=None, max_length=100000)


class BundleCreate(BaseModel):
    items: list[BundleItemCreate] = Field(min_length=2)
    thesis: str | None = Field(default=None, max_length=100000)
    ordered: bool = False


class BundleItemView(ORM):
    id: UUID
    signal_id: UUID
    position: int
    note: str | None
    signal: SignalView


class BundleView(ORM):
    id: UUID
    thesis: str | None
    ordered: bool
    status: ProcessingStatus
    latest_evidence_id: UUID | None
    archived_at: datetime | None
    items: list[BundleItemView]
    created_at: datetime


class Accepted(BaseModel):
    aggregate_type: str
    aggregate_id: UUID
    operation_id: UUID
    status_url: str


class DocumentContent(ORM):
    id: UUID
    document_id: UUID
    canonical_url: str
    media_type: str
    retrieved_at: datetime
    content_sha256: str
    normalized_text_length: int
    segments: list[dict[str, Any]]
    text: str


class HighlightCreate(BaseModel):
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    text_verbatim: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_span(self):
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


class HighlightView(ORM):
    id: UUID
    signal_id: UUID
    document_version_id: UUID
    kind: HighlightKind
    start_offset: int
    end_offset: int
    text_verbatim: str
    tombstoned_at: datetime | None
    created_at: datetime


class EdgeView(ORM):
    id: UUID
    source_type: str
    source_id: UUID
    target_type: str
    target_id: UUID
    kind: EdgeKind
    weight: float | None
    revision: int
    model_profile: str | None


class StageView(ORM):
    id: UUID
    name: str
    attempt: int
    status: StageStatus
    error: dict[str, Any] | None
    started_at: datetime | None
    completed_at: datetime | None
    next_retry_at: datetime | None


class OperationView(ORM):
    id: UUID
    aggregate_type: str
    aggregate_id: UUID
    kind: str
    status: OperationStatus
    error: dict[str, Any] | None
    completed_at: datetime | None
    created_at: datetime
    stages: list[StageView] = Field(default_factory=list)


class RetryResponse(BaseModel):
    operation_id: UUID
    status_url: str
