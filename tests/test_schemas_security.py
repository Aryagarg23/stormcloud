from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from stormcloud.models import Role
from stormcloud.schemas import CommentCreate, GradeArticleInput, HighlightCreate, OperationView
from stormcloud.security import hash_password, require_admin, token_hash, verify_password


def test_highlight_schema_rejects_non_forward_range() -> None:
    with pytest.raises(ValidationError, match="end_offset must be greater"):
        HighlightCreate(start_offset=5, end_offset=5, text_verbatim="x")


def test_comment_schema_trims_and_rejects_blank_text() -> None:
    assert CommentCreate(body="  useful context  ").body == "useful context"
    with pytest.raises(ValidationError, match="Comment cannot be empty"):
        CommentCreate(body="   ")


@pytest.mark.parametrize("grade", [1, 2, 3, 4, None])
def test_grading_schema_accepts_four_tiers_and_ungraded(grade) -> None:
    assert GradeArticleInput(grade=grade, expected_revision="0").grade == grade


@pytest.mark.parametrize("grade", [0, 5])
def test_grading_schema_rejects_out_of_range_tiers(grade) -> None:
    with pytest.raises(ValidationError):
        GradeArticleInput(grade=grade)


def test_grading_revision_is_an_opaque_non_negative_integer_string() -> None:
    assert GradeArticleInput(grade=1, expected_revision="12").expected_revision == "12"
    for invalid in ("-1", "1.0", "current", ""):
        with pytest.raises(ValidationError, match="non-negative integer string"):
            GradeArticleInput(grade=1, expected_revision=invalid)


def test_role_dependency_allows_admin_and_rejects_member() -> None:
    admin = SimpleNamespace(role=Role.admin)
    member = SimpleNamespace(role=Role.member)
    assert require_admin(admin) is admin
    with pytest.raises(HTTPException) as exc:
        require_admin(member)
    assert exc.value.status_code == 403


def test_password_and_opaque_tokens_are_not_stored_verbatim() -> None:
    password = "correct horse battery staple"
    digest = hash_password(password)
    assert password not in digest
    assert verify_password(password, digest)
    assert not verify_password("wrong password", digest)
    assert not verify_password(password, "malformed")
    assert token_hash("invite-token") != "invite-token"
    assert token_hash("invite-token") == token_hash("invite-token")


def test_operation_stages_are_not_shared_between_instances() -> None:
    values = {
        "id": uuid4(),
        "aggregate_type": "signal",
        "aggregate_id": uuid4(),
        "kind": "ingest",
        "status": "pending",
        "error": None,
        "completed_at": None,
        "created_at": "2026-09-04T00:00:00Z",
    }
    first = OperationView.model_validate(values)
    second = OperationView.model_validate({**values, "id": uuid4()})
    assert first.stages == second.stages == []
    assert first.stages is not second.stages
