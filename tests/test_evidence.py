from __future__ import annotations

import pytest

from stormcloud.evidence import (
    BundleMemberEvidence,
    EvidenceSpan,
    assemble_bundle_evidence,
    assemble_signal_evidence,
    content_addressed_key,
    validate_span,
)


def span(*, id: str, source_id: str, start: int, end: int, text: str, origin: str = "human"):
    return EvidenceSpan(
        id=id,
        source_id=source_id,
        source_kind="document",
        start=start,
        end=end,
        text=text,
        origin=origin,
    )


def test_exact_span_must_match_source_text_and_offsets() -> None:
    source_id = "document:doc-1"
    valid = span(id="h1", source_id=source_id, start=6, end=11, text="world")
    validate_span(valid, {source_id: "hello world"})

    with pytest.raises(ValueError, match="exact source span"):
        validate_span(valid.model_copy(update={"text": "WORLD"}), {source_id: "hello world"})

    with pytest.raises(ValueError, match="exact source span"):
        validate_span(valid.model_copy(update={"end": 12}), {source_id: "hello world"})


def test_signal_evidence_is_deterministic_and_excludes_inactive_spans() -> None:
    source_id = "document:doc-1"
    active = span(id="b", source_id=source_id, start=6, end=11, text="world")
    suppressed = span(id="a", source_id=source_id, start=0, end=5, text="hello").model_copy(
        update={"suppressed": True}
    )
    kwargs = {
        "signal_id": "sig-1",
        "description_verbatim": "Research note",
        "document_id": "doc-1",
        "document_text": "hello world",
        "human_highlights": [active, suppressed],
    }

    first = assemble_signal_evidence(**kwargs)
    second = assemble_signal_evidence(**kwargs)

    assert first.content_sha256 == second.content_sha256
    assert first.object_key == second.object_key
    assert "world" in first.evidence_text
    assert "hello\n" not in first.evidence_text
    assert [item["id"] for item in first.manifest["active_spans"]] == ["b"]


def test_bundle_evidence_preserves_explicit_position_order() -> None:
    members = [
        BundleMemberEvidence(
            signal_id="sig-2", evidence_version_id="ev-2", evidence_text="second", position=1
        ),
        BundleMemberEvidence(
            signal_id="sig-1", evidence_version_id="ev-1", evidence_text="first", position=0
        ),
    ]

    result = assemble_bundle_evidence(bundle_id="bundle-1", members=members, ordered=True)

    assert result.evidence_text.index("sig-1") < result.evidence_text.index("sig-2")
    assert [member["signal_id"] for member in result.manifest["members"]] == ["sig-1", "sig-2"]
    assert result.manifest["ordered"] is True


def test_bundle_requires_usable_evidence_for_every_member() -> None:
    with pytest.raises(ValueError, match="all bundle members"):
        assemble_bundle_evidence(
            bundle_id="bundle-1",
            members=[
                BundleMemberEvidence(
                    signal_id="sig-1", evidence_version_id="ev-1", evidence_text=" ", position=0
                )
            ],
        )


def test_content_addressed_key_is_stable_and_namespace_safe() -> None:
    first = content_addressed_key("/raw/source/", b"same bytes")
    second = content_addressed_key("raw/source", b"same bytes")
    assert first == second
    assert first.startswith("raw/source/sha256/")
