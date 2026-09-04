import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

STREAM_SUBJECTS = ["stormcloud.>"]

@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    schema_version: int
    subject: str
    aggregate_type: str
    aggregate_id: str
    correlation_id: str
    causation_id: str | None
    occurred_at: str
    payload: dict[str, Any]

    @classmethod
    def create(cls, subject: str, aggregate_type: str, aggregate_id: str | uuid.UUID,
               payload: dict[str, Any], *, correlation_id: str | None = None,
               causation_id: str | None = None) -> "EventEnvelope":
        event_id = str(uuid.uuid4())
        return cls(event_id, 1, subject, aggregate_type, str(aggregate_id),
                   correlation_id or event_id, causation_id,
                   datetime.now(UTC).isoformat(), payload)

    def encode(self) -> bytes:
        return json.dumps(asdict(self), separators=(",", ":")).encode()

    @classmethod
    def decode(cls, data: bytes) -> "EventEnvelope":
        return cls(**json.loads(data))

def enqueue(session: Session, event: EventEnvelope) -> None:
    from stormcloud.models import OutboxEvent
    session.add(OutboxEvent(
        event_id=uuid.UUID(event.event_id), subject=event.subject,
        aggregate_type=event.aggregate_type, aggregate_id=uuid.UUID(event.aggregate_id),
        correlation_id=uuid.UUID(event.correlation_id),
        causation_id=uuid.UUID(event.causation_id) if event.causation_id else None,
        payload=asdict(event)))

def claim_inbox(session: Session, consumer: str, event: EventEnvelope) -> bool:
    from stormcloud.models import InboxEvent
    existing = session.scalar(select(InboxEvent).where(
        InboxEvent.consumer == consumer,
        InboxEvent.event_id == uuid.UUID(event.event_id)))
    if existing:
        return False
    session.add(InboxEvent(consumer=consumer, event_id=uuid.UUID(event.event_id)))
    session.flush()
    return True
