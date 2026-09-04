from __future__ import annotations
import hashlib
from datetime import timedelta
from typing import Annotated
from urllib.parse import quote
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload
from .config import get_settings
from .db import get_db
from .models import Bundle, BundleItem, DocumentVersion, Edge, EdgeKind, Highlight, HighlightKind, HighlightSuppression, IdempotencyRecord, Invitation, Operation, OperationStatus, OutboxEvent, ProcessingStage, ProcessingStatus, RefreshSession, Role, Signal, StageStatus, User, new_id
from .schemas import Accepted, BundleCreate, BundleView, DocumentContent, EdgeView, HighlightCreate, HighlightView, InvitationCreate, InvitationIssued, InvitationView, InviteAccept, LoginRequest, OperationView, RefreshRequest, SignalCreate, SignalView, StageView, TokenPair, UserPatch, UserView
from .security import AdminUser, CurrentUser, create_access_token, hash_password, opaque_token, token_hash, utcnow, verify_password
from .storage import ObjectStore

router = APIRouter(prefix="/v1")
DB = Annotated[Session, Depends(get_db)]

def fail(code: int, detail: str):
    raise HTTPException(status_code=code, detail=detail)

def queue(db: Session, subject: str, kind: str, aggregate_type: str,
          aggregate_id: UUID, user_id: UUID | None, extra: dict | None = None) -> Operation:
    operation = Operation(aggregate_type=aggregate_type, aggregate_id=aggregate_id,
                          kind=kind, requested_by_id=user_id, status=OperationStatus.pending)
    db.add(operation)
    db.flush()
    event_id = new_id()
    full_subject = subject if subject.startswith("stormcloud.") else f"stormcloud.{subject}.v1"
    db.add(OutboxEvent(event_id=event_id, subject=full_subject,
        aggregate_type=aggregate_type, aggregate_id=aggregate_id,
        correlation_id=operation.id,
        payload={"event_id": str(event_id), "operation_id": str(operation.id),
                 "aggregate_type": aggregate_type, "aggregate_id": str(aggregate_id),
                 **(extra or {})}))
    return operation

def accepted(operation: Operation) -> Accepted:
    return Accepted(aggregate_type=operation.aggregate_type,
                    aggregate_id=operation.aggregate_id,
                    operation_id=operation.id,
                    status_url=f"/v1/operations/{operation.id}")

def request_digest(body: BaseModel) -> str:
    return hashlib.sha256(body.model_dump_json(exclude_none=False).encode()).hexdigest()

def remembered(db: Session, user: User, key: str | None, body: BaseModel):
    if not key:
        return None
    row = db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user.id, IdempotencyRecord.key == key))
    if not row:
        return None
    if row.request_hash != request_digest(body):
        fail(409, "Idempotency-Key was already used for a different request")
    return Accepted.model_validate(row.response_body)

def remember(db: Session, user: User, key: str | None,
             body: BaseModel, result: Accepted):
    if key:
        db.add(IdempotencyRecord(user_id=user.id, key=key,
            request_hash=request_digest(body), status_code=202,
            response_body=result.model_dump(mode="json")))

@router.post("/auth/login", response_model=TokenPair)
def login(body: LoginRequest, db: DB):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        fail(401, "Invalid email or password")
    access, ttl = create_access_token(user)
    raw = opaque_token()
    settings = get_settings()
    db.add(RefreshSession(user_id=user.id, token_hash=token_hash(raw),
                          expires_at=utcnow() + timedelta(days=settings.refresh_token_days)))
    db.commit()
    return TokenPair(access_token=access, refresh_token=raw, expires_in=ttl)

@router.post("/auth/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: DB):
    old = db.scalar(select(RefreshSession).where(
        RefreshSession.token_hash == token_hash(body.refresh_token)).with_for_update())
    if not old or old.revoked_at or old.expires_at <= utcnow():
        fail(401, "Invalid or expired refresh token")
    user = db.get(User, old.user_id)
    if not user or not user.is_active:
        fail(401, "Inactive or unknown user")
    raw = opaque_token()
    settings = get_settings()
    new = RefreshSession(user_id=user.id, token_hash=token_hash(raw),
                         expires_at=utcnow() + timedelta(days=settings.refresh_token_days))
    db.add(new)
    db.flush()
    old.revoked_at = utcnow()
    old.replaced_by_id = new.id
    access, ttl = create_access_token(user)
    db.commit()
    return TokenPair(access_token=access, refresh_token=raw, expires_in=ttl)

@router.post("/auth/logout", status_code=204)
def logout(body: RefreshRequest, db: DB):
    row = db.scalar(select(RefreshSession).where(
        RefreshSession.token_hash == token_hash(body.refresh_token)))
    if row and not row.revoked_at:
        row.revoked_at = utcnow()
        db.commit()

@router.get("/auth/me", response_model=UserView)
def me(user: CurrentUser):
    return user

@router.post("/auth/accept-invite", response_model=TokenPair)
def accept_invite(body: InviteAccept, db: DB):
    invitation = db.scalar(select(Invitation).where(
        Invitation.token_hash == token_hash(body.token)).with_for_update())
    if not invitation or invitation.revoked_at or invitation.accepted_at or invitation.expires_at <= utcnow():
        fail(400, "Invalid or expired invitation")
    if db.scalar(select(User).where(func.lower(User.email) == invitation.email.lower())):
        fail(409, "A user with that email already exists")
    user = User(email=invitation.email.lower(), password_hash=hash_password(body.password),
                role=invitation.role)
    db.add(user)
    db.flush()
    invitation.accepted_at = utcnow()
    raw = opaque_token()
    settings = get_settings()
    db.add(RefreshSession(user_id=user.id, token_hash=token_hash(raw),
                          expires_at=utcnow() + timedelta(days=settings.refresh_token_days)))
    access, ttl = create_access_token(user)
    db.commit()
    return TokenPair(access_token=access, refresh_token=raw, expires_in=ttl)

@router.post("/admin/invitations", response_model=InvitationIssued, status_code=201)
def invite(body: InvitationCreate, admin: AdminUser, db: DB):
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        fail(409, "User already exists")
    raw = opaque_token()
    settings = get_settings()
    invitation = Invitation(email=body.email.lower(), role=body.role,
        token_hash=token_hash(raw),
        expires_at=utcnow() + timedelta(hours=settings.invitation_hours),
        invited_by_id=admin.id)
    db.add(invitation)
    db.flush()
    url = f"{settings.invite_accept_url}?token={quote(raw)}"
    queue(db, "mail.invitation.requested", "invite", "invitation", invitation.id,
          admin.id, {"email": invitation.email, "invite_url": url})
    db.commit()
    db.refresh(invitation)
    return InvitationIssued(**InvitationView.model_validate(invitation).model_dump(),
        invite_url=url, token=raw if settings.debug_return_invite_token else None)

@router.get("/admin/invitations", response_model=list[InvitationView])
def invitations(admin: AdminUser, db: DB):
    return list(db.scalars(select(Invitation).order_by(Invitation.created_at.desc())))

@router.delete("/admin/invitations/{invite_id}", status_code=204)
def revoke_invite(invite_id: UUID, admin: AdminUser, db: DB):
    invitation = db.get(Invitation, invite_id)
    if not invitation:
        fail(404, "Invitation not found")
    invitation.revoked_at = invitation.revoked_at or utcnow()
    db.commit()

@router.get("/admin/users", response_model=list[UserView])
def users(admin: AdminUser, db: DB):
    return list(db.scalars(select(User).order_by(User.email)))

@router.patch("/admin/users/{user_id}", response_model=UserView)
def update_user(user_id: UUID, body: UserPatch, admin: AdminUser, db: DB):
    user = db.get(User, user_id)
    if not user:
        fail(404, "User not found")
    if user.id == admin.id and body.is_active is False:
        fail(409, "You cannot deactivate your own account")
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    return user

@router.post("/signals", response_model=Accepted, status_code=202)
def create_signal(body: SignalCreate, user: CurrentUser, db: DB,
                  idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    if old := remembered(db, user, idempotency_key, body):
        return old
    signal = Signal(submitted_url=str(body.url),
                    description_verbatim=body.description_verbatim,
                    created_by_id=user.id)
    db.add(signal)
    db.flush()
    operation = queue(db, "signal.submitted", "ingest", "signal", signal.id,
                      user.id, {"url": signal.submitted_url})
    result = accepted(operation)
    remember(db, user, idempotency_key, body, result)
    db.commit()
    return result

@router.get("/signals", response_model=list[SignalView])
def list_signals(user: CurrentUser, db: DB, status_filter: ProcessingStatus | None = None,
                 include_archived: bool = False, limit: int = 50, offset: int = 0):
    query = select(Signal).order_by(Signal.created_at.desc()).limit(min(limit, 200)).offset(offset)
    if status_filter:
        query = query.where(Signal.status == status_filter)
    if not include_archived:
        query = query.where(Signal.archived_at.is_(None))
    return list(db.scalars(query))

@router.get("/signals/{signal_id}", response_model=SignalView)
def get_signal(signal_id: UUID, user: CurrentUser, db: DB):
    row = db.get(Signal, signal_id)
    if not row:
        fail(404, "Signal not found")
    return row

@router.post("/signals/{signal_id}/retry", response_model=Accepted, status_code=202)
def retry_signal(signal_id: UUID, user: CurrentUser, db: DB):
    row = db.get(Signal, signal_id)
    if not row:
        fail(404, "Signal not found")
    row.status = ProcessingStatus.pending
    operation = queue(db, "signal.retry.requested", "retry", "signal", row.id, user.id)
    db.commit()
    return accepted(operation)

@router.post("/signals/{signal_id}/archive", status_code=204)
def archive_signal(signal_id: UUID, user: CurrentUser, db: DB):
    row = db.get(Signal, signal_id)
    if not row:
        fail(404, "Signal not found")
    row.archived_at = utcnow()
    row.status = ProcessingStatus.archived
    db.commit()

@router.get("/signals/{signal_id}/neighbors", response_model=list[EdgeView])
def signal_neighbors(signal_id: UUID, user: CurrentUser, db: DB, limit: int = 25):
    return list(db.scalars(select(Edge).where(
        Edge.source_type == "signal", Edge.source_id == signal_id,
        Edge.kind == EdgeKind.similarity).order_by(Edge.weight.desc()).limit(min(limit, 100))))

@router.post("/bundles", response_model=Accepted, status_code=202)
def create_bundle(body: BundleCreate, user: CurrentUser, db: DB,
                  idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    if old := remembered(db, user, idempotency_key, body):
        return old
    bundle = Bundle(thesis=body.thesis, ordered=body.ordered, created_by_id=user.id)
    db.add(bundle)
    db.flush()
    signals = []
    for position, item in enumerate(body.items):
        signal = Signal(submitted_url=str(item.url),
                        description_verbatim=item.description_verbatim,
                        created_by_id=user.id)
        db.add(signal)
        db.flush()
        db.add(BundleItem(bundle_id=bundle.id, signal_id=signal.id,
                          position=position, note=item.note))
        signals.append(signal)
        queue(db, "signal.submitted", "ingest", "signal", signal.id, user.id,
              {"url": signal.submitted_url, "bundle_id": str(bundle.id)})
    if body.ordered:
        for left, right in zip(signals, signals[1:]):
            db.add(Edge(source_type="signal", source_id=left.id,
                        target_type="signal", target_id=right.id,
                        kind=EdgeKind.next, revision=1))
    operation = queue(db, "bundle.submitted", "ingest", "bundle", bundle.id, user.id)
    result = accepted(operation)
    remember(db, user, idempotency_key, body, result)
    db.commit()
    return result

@router.get("/bundles", response_model=list[BundleView])
def list_bundles(user: CurrentUser, db: DB, include_archived: bool = False,
                 limit: int = 50, offset: int = 0):
    query = select(Bundle).options(
        selectinload(Bundle.items).selectinload(BundleItem.signal)
    ).order_by(Bundle.created_at.desc()).limit(min(limit, 200)).offset(offset)
    if not include_archived:
        query = query.where(Bundle.archived_at.is_(None))
    return list(db.scalars(query).unique())

@router.get("/bundles/{bundle_id}", response_model=BundleView)
def get_bundle(bundle_id: UUID, user: CurrentUser, db: DB):
    row = db.scalar(select(Bundle).where(Bundle.id == bundle_id).options(
        selectinload(Bundle.items).selectinload(BundleItem.signal)))
    if not row:
        fail(404, "Bundle not found")
    return row

@router.post("/bundles/{bundle_id}/retry", response_model=Accepted, status_code=202)
def retry_bundle(bundle_id: UUID, user: CurrentUser, db: DB):
    row = db.get(Bundle, bundle_id)
    if not row:
        fail(404, "Bundle not found")
    row.status = ProcessingStatus.pending
    operation = queue(db, "bundle.retry.requested", "retry", "bundle", row.id, user.id)
    db.commit()
    return accepted(operation)

@router.post("/bundles/{bundle_id}/archive", status_code=204)
def archive_bundle(bundle_id: UUID, user: CurrentUser, db: DB):
    row = db.get(Bundle, bundle_id)
    if not row:
        fail(404, "Bundle not found")
    row.archived_at = utcnow()
    row.status = ProcessingStatus.archived
    db.commit()

@router.get("/bundles/{bundle_id}/neighbors", response_model=list[EdgeView])
def bundle_neighbors(bundle_id: UUID, user: CurrentUser, db: DB, limit: int = 25):
    return list(db.scalars(select(Edge).where(
        Edge.source_type == "bundle", Edge.source_id == bundle_id,
        Edge.kind == EdgeKind.similarity).order_by(Edge.weight.desc()).limit(min(limit, 100))))

@router.get("/documents/{version_id}", response_model=DocumentContent)
def get_document(version_id: UUID, user: CurrentUser, db: DB):
    row = db.get(DocumentVersion, version_id)
    if not row:
        fail(404, "Document version not found")
    text = ObjectStore().get_bytes(get_settings().s3_bucket_normalized,
                                   row.normalized_object_key).decode()
    return DocumentContent.model_validate(row).model_copy(update={"text": text})

@router.get("/signals/{signal_id}/highlights", response_model=list[HighlightView])
def list_highlights(signal_id: UUID, user: CurrentUser, db: DB):
    return list(db.scalars(select(Highlight).where(
        Highlight.signal_id == signal_id, Highlight.tombstoned_at.is_(None))
        .order_by(Highlight.start_offset)))

@router.post("/signals/{signal_id}/highlights", response_model=Accepted, status_code=202)
def add_highlight(signal_id: UUID, body: HighlightCreate, user: CurrentUser, db: DB):
    signal = db.get(Signal, signal_id)
    if not signal or not signal.document_version_id:
        fail(409 if signal else 404, "Signal has no normalized document yet" if signal else "Signal not found")
    document = db.get(DocumentVersion, signal.document_version_id)
    text = ObjectStore().get_bytes(get_settings().s3_bucket_normalized,
                                   document.normalized_object_key).decode()
    if body.end_offset > len(text) or text[body.start_offset:body.end_offset] != body.text_verbatim:
        fail(422, "Highlight must be an exact normalized-document span")
    highlight = Highlight(signal_id=signal.id, document_version_id=document.id,
        kind=HighlightKind.human, start_offset=body.start_offset,
        end_offset=body.end_offset, text_verbatim=body.text_verbatim,
        text_sha256=hashlib.sha256(body.text_verbatim.encode()).hexdigest(),
        created_by_id=user.id)
    db.add(highlight)
    db.flush()
    operation = queue(db, "highlight.changed", "rebuild_evidence", "signal",
                      signal.id, user.id, {"highlight_id": str(highlight.id)})
    db.commit()
    return accepted(operation)

@router.delete("/signals/{signal_id}/highlights/{highlight_id}", response_model=Accepted, status_code=202)
def delete_highlight(signal_id: UUID, highlight_id: UUID, user: CurrentUser, db: DB):
    highlight = db.get(Highlight, highlight_id)
    if not highlight or highlight.signal_id != signal_id:
        fail(404, "Highlight not found")
    if highlight.kind != HighlightKind.human:
        fail(409, "Automatic highlights must be suppressed")
    highlight.tombstoned_at = highlight.tombstoned_at or utcnow()
    operation = queue(db, "highlight.changed", "rebuild_evidence", "signal",
                      signal_id, user.id, {"highlight_id": str(highlight.id)})
    db.commit()
    return accepted(operation)

@router.post("/signals/{signal_id}/auto-highlights/{highlight_id}/suppress", response_model=Accepted, status_code=202)
def suppress(signal_id: UUID, highlight_id: UUID, user: CurrentUser, db: DB):
    highlight = db.get(Highlight, highlight_id)
    if not highlight or highlight.signal_id != signal_id or highlight.kind != HighlightKind.automatic:
        fail(404, "Automatic highlight not found")
    row = db.scalar(select(HighlightSuppression).where(
        HighlightSuppression.signal_id == signal_id,
        HighlightSuppression.highlight_id == highlight_id))
    if row:
        row.restored_at = None
    else:
        db.add(HighlightSuppression(signal_id=signal_id, highlight_id=highlight_id,
                                    created_by_id=user.id))
    operation = queue(db, "highlight.changed", "rebuild_evidence", "signal",
                      signal_id, user.id, {"action": "suppress"})
    db.commit()
    return accepted(operation)

@router.delete("/signals/{signal_id}/auto-highlights/{highlight_id}/suppress", response_model=Accepted, status_code=202)
def restore(signal_id: UUID, highlight_id: UUID, user: CurrentUser, db: DB):
    row = db.scalar(select(HighlightSuppression).where(
        HighlightSuppression.signal_id == signal_id,
        HighlightSuppression.highlight_id == highlight_id,
        HighlightSuppression.restored_at.is_(None)))
    if not row:
        fail(404, "Active suppression not found")
    row.restored_at = utcnow()
    operation = queue(db, "highlight.changed", "rebuild_evidence", "signal",
                      signal_id, user.id, {"action": "restore"})
    db.commit()
    return accepted(operation)

@router.get("/operations/{operation_id}", response_model=OperationView)
def operation(operation_id: UUID, user: CurrentUser, db: DB):
    row = db.scalar(select(Operation).where(Operation.id == operation_id)
                    .options(selectinload(Operation.stages)))
    if not row:
        fail(404, "Operation not found")
    return row

@router.get("/operations", response_model=list[OperationView])
def operations(user: CurrentUser, db: DB, status_filter: OperationStatus | None = None,
               limit: int = 50):
    query = select(Operation).options(selectinload(Operation.stages)).order_by(
        Operation.created_at.desc()).limit(min(limit, 200))
    if status_filter:
        query = query.where(Operation.status == status_filter)
    return list(db.scalars(query))

@router.get("/admin/dead-letters", response_model=list[StageView])
def dead_letters(admin: AdminUser, db: DB, limit: int = 100):
    return list(db.scalars(select(ProcessingStage).where(
        ProcessingStage.status == StageStatus.dead_lettered)
        .order_by(ProcessingStage.created_at.desc()).limit(min(limit, 500))))

@router.post("/admin/dead-letters/{stage_id}/retry", response_model=Accepted, status_code=202)
def retry_dead_letter(stage_id: UUID, admin: AdminUser, db: DB):
    stage = db.get(ProcessingStage, stage_id)
    if not stage or stage.status != StageStatus.dead_lettered:
        fail(404, "Dead-lettered stage not found")
    original = db.get(Operation, stage.operation_id)
    stage.status = StageStatus.pending
    operation = queue(db, "operation.retry.requested", "retry",
                      original.aggregate_type, original.aggregate_id, admin.id,
                      {"operation_id": str(original.id), "stage": stage.name})
    db.commit()
    return accepted(operation)
