from __future__ import annotations

import hashlib
import html
from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import (
    ArticleGrade,
    ArticleGradeEvent,
    DocumentVersion,
    IdempotencyRecord,
    Signal,
    User,
)
from .schemas import (
    ArticleGradeActor,
    ArticleGradeCard,
    GradeArticleInput,
    GradingBoard,
)
from .security import CurrentUser
from .storage import ObjectStore

router = APIRouter(prefix="/v1")
DB = Annotated[Session, Depends(get_db)]


def _title(signal: Signal, document: DocumentVersion | None) -> str:
    if document:
        value = document.metadata_json.get("title")
        if isinstance(value, str) and value.strip():
            return value.strip()[:300]
    parsed = urlparse(document.canonical_url if document else signal.submitted_url)
    return parsed.hostname or "Untitled article"


def _card(
    signal: Signal,
    grade: ArticleGrade | None,
    actor: User | None,
    document: DocumentVersion | None,
) -> ArticleGradeCard:
    grade_actor = ArticleGradeActor(id=actor.id, email=actor.email) if actor is not None else None
    return ArticleGradeCard(
        id=signal.id,
        url=signal.submitted_url,
        canonical_url=document.canonical_url if document else None,
        title=_title(signal, document),
        thumbnail_url=f"/v1/signals/{signal.id}/thumbnail",
        grade=grade.grade if grade else None,
        graded_by=grade_actor,
        updated_by=grade_actor,
        updated_at=grade.updated_at if grade else signal.updated_at,
        revision=str(grade.revision if grade else 0),
    )


def _load_card(db: Session, signal: Signal, grade: ArticleGrade | None) -> ArticleGradeCard:
    document = (
        db.get(DocumentVersion, signal.document_version_id) if signal.document_version_id else None
    )
    actor = db.get(User, grade.graded_by_id) if grade else None
    return _card(signal, grade, actor, document)


@router.get("/articles/grading-board", response_model=GradingBoard)
def grading_board(user: CurrentUser, db: DB):
    rows = db.execute(
        select(Signal, ArticleGrade, User, DocumentVersion)
        .select_from(Signal)
        .outerjoin(ArticleGrade, ArticleGrade.signal_id == Signal.id)
        .outerjoin(User, User.id == ArticleGrade.graded_by_id)
        .outerjoin(DocumentVersion, DocumentVersion.id == Signal.document_version_id)
        .where(Signal.archived_at.is_(None))
        .order_by(Signal.created_at.desc())
    ).all()

    ungraded: list[ArticleGradeCard] = []
    tiers: dict[str, list[ArticleGradeCard]] = {str(value): [] for value in range(1, 5)}
    revision_parts: list[str] = []
    for signal, grade, actor, document in rows:
        card = _card(signal, grade, actor, document)
        revision_parts.append(f"{signal.id}:{card.revision}:{card.grade}")
        if card.grade is None:
            ungraded.append(card)
        else:
            tiers[str(card.grade)].append(card)
    board_revision = hashlib.sha256("|".join(revision_parts).encode()).hexdigest()
    return GradingBoard(ungraded=ungraded, tiers=tiers, revision=board_revision)


@router.put("/signals/{signal_id}/grade", response_model=ArticleGradeCard)
def update_grade(
    signal_id: UUID,
    body: GradeArticleInput,
    user: CurrentUser,
    db: DB,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    request_hash = hashlib.sha256(body.model_dump_json(exclude_none=False).encode()).hexdigest()
    stored_key = (
        "grade:" + str(signal_id) + ":" + hashlib.sha256(idempotency_key.encode()).hexdigest()
        if idempotency_key
        else None
    )
    if stored_key:
        saved = db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == user.id,
                IdempotencyRecord.key == stored_key,
            )
        )
        if saved:
            if saved.request_hash != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used for a different grade",
                )
            return ArticleGradeCard.model_validate(saved.response_body)

    signal = db.scalar(select(Signal).where(Signal.id == signal_id).with_for_update())
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    grade = db.scalar(
        select(ArticleGrade).where(ArticleGrade.signal_id == signal_id).with_for_update()
    )
    current_revision = grade.revision if grade else 0
    if body.expected_revision is not None and int(body.expected_revision) != current_revision:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The grade changed since this board was loaded",
                "current_revision": str(current_revision),
            },
        )

    if grade is None and body.grade is None:
        card = _load_card(db, signal, None)
    elif grade is not None and grade.grade == body.grade:
        card = _load_card(db, signal, grade)
    else:
        previous_grade = grade.grade if grade else None
        next_revision = current_revision + 1
        if grade is None:
            grade = ArticleGrade(
                signal_id=signal.id,
                grade=body.grade,
                revision=next_revision,
                graded_by_id=user.id,
            )
            db.add(grade)
        else:
            grade.grade = body.grade
            grade.revision = next_revision
            grade.graded_by_id = user.id
        db.add(
            ArticleGradeEvent(
                signal_id=signal.id,
                grade=body.grade,
                previous_grade=previous_grade,
                revision=next_revision,
                changed_by_id=user.id,
            )
        )
        db.flush()
        db.refresh(grade)
        card = _load_card(db, signal, grade)

    if stored_key:
        db.add(
            IdempotencyRecord(
                user_id=user.id,
                key=stored_key,
                request_hash=request_hash,
                status_code=200,
                response_body=card.model_dump(mode="json"),
            )
        )
    db.commit()
    return card


@router.get("/signals/{signal_id}/thumbnail")
def signal_thumbnail(signal_id: UUID, user: CurrentUser, db: DB):
    signal = db.get(Signal, signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    document = (
        db.get(DocumentVersion, signal.document_version_id) if signal.document_version_id else None
    )
    if document:
        object_key = document.metadata_json.get("thumbnail_object_key")
        media_type = document.metadata_json.get("thumbnail_media_type", "image/jpeg")
        bucket = document.metadata_json.get("thumbnail_bucket", get_settings().s3_bucket_derived)
        allowed_buckets = {
            get_settings().s3_bucket_raw,
            get_settings().s3_bucket_normalized,
            get_settings().s3_bucket_derived,
        }
        if (
            isinstance(object_key, str)
            and object_key
            and isinstance(media_type, str)
            and media_type.startswith("image/")
            and bucket in allowed_buckets
        ):
            try:
                payload = ObjectStore().get_bytes(bucket, object_key)
                return Response(
                    content=payload,
                    media_type=media_type,
                    headers={
                        "Cache-Control": "private, max-age=300",
                        "X-Content-Type-Options": "nosniff",
                    },
                )
            except Exception:
                pass

    title = html.escape(_title(signal, document)[:70])
    host = html.escape(urlparse(signal.submitted_url).hostname or "source")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="270" viewBox="0 0 480 270">'
        '<rect width="480" height="270" fill="#131b2b"/>'
        '<rect x="24" y="24" width="432" height="222" rx="18" fill="#1d2940"/>'
        f'<text x="42" y="72" fill="#7dd3fc" font-family="system-ui" font-size="18">{host}</text>'
        f'<text x="42" y="126" fill="#f8fafc" font-family="system-ui" font-size="22">{title}</text>'
        '<text x="42" y="218" fill="#94a3b8" font-family="system-ui" font-size="15">Stormcloud evidence</text>'
        "</svg>"
    )
    return Response(
        content=svg.encode(),
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Security-Policy": "default-src 'none'",
            "X-Content-Type-Options": "nosniff",
        },
    )
