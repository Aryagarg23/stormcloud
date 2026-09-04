import hashlib
import re
from typing import Literal
from pydantic import BaseModel, Field

class TextSegment(BaseModel):
    id: str
    kind: Literal["paragraph", "sentence"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str

class FeatureSpan(BaseModel):
    id: str
    kind: Literal["entity", "date", "number", "noun_phrase"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str

class NLPResult(BaseModel):
    text_sha256: str
    recipe_version: str = "deterministic-nlp-v1"
    segments: list[TextSegment]
    features: list[FeatureSpan]

def normalize_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)
    return text.strip()

def _id(kind: str, start: int, end: int, text: str) -> str:
    source = f"{kind}|{start}|{end}|{text}".encode()
    return f"{kind[:1]}_{hashlib.sha256(source).hexdigest()[:20]}"

def _segment(kind: Literal["paragraph", "sentence"], text: str,
             start: int, end: int) -> TextSegment:
    return TextSegment(id=_id(kind, start, end, text[start:end]), kind=kind,
                       start=start, end=end, text=text[start:end])

def segment_text(text: str) -> list[TextSegment]:
    segments: list[TextSegment] = []
    paragraphs: list[tuple[int, int]] = []
    for match in re.finditer(r"[^\n](?:.*?[^\n])?(?=\n\s*\n|$)", text, re.DOTALL):
        start, end = match.span()
        while start < end and text[start].isspace(): start += 1
        while end > start and text[end - 1].isspace(): end -= 1
        if end > start:
            paragraphs.append((start, end))
            segments.append(_segment("paragraph", text, start, end))
    for p_start, p_end in paragraphs:
        paragraph = text[p_start:p_end]
        for match in re.finditer(r"[^.!?]+(?:[.!?]+(?=\s|$)|$)", paragraph):
            start, end = p_start + match.start(), p_start + match.end()
            while start < end and text[start].isspace(): start += 1
            while end > start and text[end - 1].isspace(): end -= 1
            if end > start:
                segments.append(_segment("sentence", text, start, end))
    return sorted(segments, key=lambda item: (item.start, item.kind != "paragraph", item.end))

def analyze_text(raw: str) -> NLPResult:
    text = normalize_text(raw)
    patterns = (("date", r"\b(?:\d{4}-\d{2}-\d{2}|\d{4})\b"),
                ("number", r"(?<!\w)[+-]?(?:\d[\d,]*)(?:\.\d+)?%?"),
                ("entity", r"\b(?:[A-Z][a-z]+|[A-Z]{2,})(?:[ \t]+(?:[A-Z][a-z]+|[A-Z]{2,})){0,4}\b"),
                ("noun_phrase", r"\b(?:[A-Za-z][A-Za-z'-]{2,}[ \t]+){1,3}[A-Za-z][A-Za-z'-]{2,}\b"))
    features = []
    for kind, pattern in patterns:
        for match in re.finditer(pattern, text):
            features.append(FeatureSpan(id=_id(kind, *match.span(), match.group()),
                                        kind=kind, start=match.start(), end=match.end(),
                                        text=match.group()))
    features.sort(key=lambda item: (item.start, item.end, item.kind))
    return NLPResult(text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                     segments=segment_text(text), features=features)
