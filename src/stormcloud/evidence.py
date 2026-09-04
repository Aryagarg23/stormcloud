import hashlib
import json
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class EvidenceSpan(BaseModel):
    id: str
    source_id: str
    source_kind: Literal["description", "document"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    origin: Literal["human", "auto", "nlp"]
    tombstoned: bool = False
    suppressed: bool = False

    @model_validator(mode="after")
    def offsets(self):
        if self.end <= self.start:
            raise ValueError("evidence span end must be after start")
        return self


class EvidenceSnapshot(BaseModel):
    recipe_version: str
    evidence_text: str
    manifest: dict[str, Any]
    content_sha256: str
    object_key: str


class BundleMemberEvidence(BaseModel):
    signal_id: str
    evidence_version_id: str
    evidence_text: str
    note: str | None = None
    position: int = Field(ge=0)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def content_addressed_key(namespace: str, content: bytes | str, suffix: str = "json") -> str:
    payload = content.encode() if isinstance(content, str) else content
    digest = hashlib.sha256(payload).hexdigest()
    return f"{namespace.strip('/')}/sha256/{digest[:2]}/{digest}.{suffix.lstrip('.')}"


def validate_span(span: EvidenceSpan, sources: dict[str, str]) -> None:
    source = sources.get(span.source_id)
    if source is None or span.end > len(source) or source[span.start : span.end] != span.text:
        raise ValueError(f"span {span.id} is not an exact source span")


def assemble_signal_evidence(
    *,
    signal_id: str,
    description_verbatim: str,
    document_id: str,
    document_text: str,
    human_highlights: Sequence[EvidenceSpan] = (),
    auto_highlights: Sequence[EvidenceSpan] = (),
    source_features: Sequence[EvidenceSpan] = (),
    extraction: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    recipe_version: str = "signal-evidence-v1",
) -> EvidenceSnapshot:
    sources = {
        f"signal:{signal_id}:description": description_verbatim,
        f"document:{document_id}": document_text,
    }
    active = []
    for span in [*human_highlights, *auto_highlights, *source_features]:
        validate_span(span, sources)
        if not span.tombstoned and not span.suppressed:
            active.append(span)
    active.sort(key=lambda item: (item.source_kind, item.start, item.end, item.id))
    sections = [f"RESEARCHER DESCRIPTION\n{description_verbatim}"] if description_verbatim else []
    selected = [span.text for span in active if span.origin in {"human", "auto"}]
    features = [span.text for span in active if span.origin == "nlp"]
    if selected:
        sections.append("SELECTED SOURCE EVIDENCE\n" + "\n".join(selected))
    if features:
        sections.append("SOURCE FEATURES\n" + "\n".join(features))
    manifest = {
        "kind": "signal",
        "signal_id": signal_id,
        "document_id": document_id,
        "description_sha256": hashlib.sha256(description_verbatim.encode()).hexdigest(),
        "active_spans": [item.model_dump(mode="json") for item in active],
        "extraction": extraction or {},
        "provenance": provenance or {},
        "recipe_version": recipe_version,
    }
    evidence_text = "\n\n".join(sections)
    envelope = _canonical({"manifest": manifest, "evidence_text": evidence_text})
    digest = hashlib.sha256(envelope).hexdigest()
    return EvidenceSnapshot(
        recipe_version=recipe_version,
        evidence_text=evidence_text,
        manifest=manifest,
        content_sha256=digest,
        object_key=content_addressed_key("evidence/signals", envelope),
    )


def assemble_bundle_evidence(
    *,
    bundle_id: str,
    members: Sequence[BundleMemberEvidence],
    thesis: str | None = None,
    ordered: bool = False,
    provenance: dict[str, Any] | None = None,
    recipe_version: str = "bundle-evidence-v1",
) -> EvidenceSnapshot:
    if not members or any(not member.evidence_text.strip() for member in members):
        raise ValueError("all bundle members must have usable evidence")
    members = sorted(members, key=lambda member: member.position)
    sections = [f"BUNDLE THESIS\n{thesis}"] if thesis and thesis.strip() else []
    sections.extend(
        f"MEMBER {m.position + 1} [{m.signal_id}]\n"
        + (f"NOTE: {m.note}\n" if m.note else "")
        + m.evidence_text
        for m in members
    )
    manifest = {
        "kind": "bundle",
        "bundle_id": bundle_id,
        "thesis": thesis,
        "ordered": ordered,
        "members": [m.model_dump(exclude={"evidence_text"}) for m in members],
        "provenance": provenance or {},
        "recipe_version": recipe_version,
    }
    evidence_text = "\n\n".join(sections)
    envelope = _canonical({"manifest": manifest, "evidence_text": evidence_text})
    return EvidenceSnapshot(
        recipe_version=recipe_version,
        evidence_text=evidence_text,
        manifest=manifest,
        content_sha256=hashlib.sha256(envelope).hexdigest(),
        object_key=content_addressed_key("evidence/bundles", envelope),
    )
