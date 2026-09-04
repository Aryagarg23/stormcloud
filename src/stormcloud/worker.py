from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

import nats
import structlog
from nats.js.api import AckPolicy, ConsumerConfig, StreamConfig
from sqlalchemy import select

from .config import get_settings
from .db import session_scope
from .events import EventEnvelope, claim_inbox
from .models import (
    Bundle,
    BundleItem,
    Operation,
    OperationStatus,
    OutboxEvent,
    ProcessingStatus,
    Signal,
    StageStatus,
)
from .observability import configure_logging
from .pipeline import (
    build_ready_bundles,
    build_signal_evidence,
    mark_stage,
    process_embedding,
    process_extraction,
    process_fetch,
    process_graph,
    process_highlighting,
    process_nlp,
    send_invitation,
)

settings = get_settings()
log = structlog.get_logger("stormcloud.worker")
Processor = Callable[[object, EventEnvelope], Awaitable[None] | None]


async def publish_outbox(js) -> None:
    while True:
        try:
            with session_scope() as session:
                rows = session.scalars(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.published_at.is_(None),
                        OutboxEvent.available_at <= datetime.now(UTC),
                    )
                    .order_by(OutboxEvent.created_at)
                    .limit(settings.worker_batch_size)
                    .with_for_update(skip_locked=True)
                ).all()
                for row in rows:
                    payload = dict(row.payload)
                    envelope = EventEnvelope(
                        event_id=str(row.event_id),
                        schema_version=row.schema_version,
                        subject=row.subject,
                        aggregate_type=row.aggregate_type,
                        aggregate_id=str(row.aggregate_id),
                        correlation_id=str(row.correlation_id),
                        causation_id=str(row.causation_id) if row.causation_id else None,
                        occurred_at=row.created_at.isoformat(),
                        payload=payload,
                    )
                    await js.publish(
                        row.subject, envelope.encode(), headers={"Nats-Msg-Id": envelope.event_id}
                    )
                    row.published_at = datetime.now(UTC)
                    row.attempts += 1
            await asyncio.sleep(settings.worker_poll_seconds)
        except Exception as exc:
            log.exception("outbox.publish_failed", error=str(exc))
            await asyncio.sleep(min(settings.worker_poll_seconds * 5, 10))


def processor_for(role: str, subject: str) -> Processor:
    if role == "fetch":
        return process_fetch
    if role == "nlp":
        return process_nlp
    if role == "llm":
        return (
            process_highlighting
            if subject == "stormcloud.document.ready.v1"
            else process_extraction
        )
    if role == "embedding":
        return process_embedding
    if role == "graph":
        return process_graph
    if role == "mailer":

        async def mail(_session, event):
            await asyncio.to_thread(send_invitation, event)

        return mail
    if role == "controller":

        async def coordinate(session, event):
            if (
                event.aggregate_type == "bundle"
                or event.subject == "stormcloud.signal.embedding.ready.v1"
            ):
                build_ready_bundles(session, event)
            else:
                build_signal_evidence(session, event)

        return coordinate
    raise ValueError(f"unknown worker role {role}")


SUBJECTS = {
    "fetch": ["stormcloud.signal.submitted.v1", "stormcloud.signal.retry.requested.v1"],
    "nlp": ["stormcloud.document.ready.v1"],
    "llm": [
        "stormcloud.signal.submitted.v1",
        "stormcloud.document.ready.v1",
        "stormcloud.signal.retry.requested.v1",
    ],
    "embedding": ["stormcloud.signal.evidence.ready.v1", "stormcloud.bundle.evidence.ready.v1"],
    "graph": ["stormcloud.signal.embedding.ready.v1", "stormcloud.bundle.embedding.ready.v1"],
    "mailer": ["stormcloud.mail.invitation.requested.v1"],
    "controller": [
        "stormcloud.researcher.ready.v1",
        "stormcloud.nlp.ready.v1",
        "stormcloud.highlights.ready.v1",
        "stormcloud.highlight.changed.v1",
        "stormcloud.signal.embedding.ready.v1",
        "stormcloud.bundle.submitted.v1",
        "stormcloud.bundle.retry.requested.v1",
    ],
}


def stage_name(role: str, subject: str) -> str:
    if role == "llm":
        return "highlighting" if subject == "stormcloud.document.ready.v1" else "extraction"
    if role == "controller":
        return "evidence"
    return role


async def mark_dead_letter(event: EventEnvelope, role: str, error: Exception) -> None:
    with session_scope() as session:
        operation_id = event.payload.get("operation_id")
        if not operation_id:
            return
        detail = {"type": type(error).__name__, "message": str(error)}
        mark_stage(
            session,
            event.payload,
            stage_name(role, event.subject),
            StageStatus.dead_lettered,
            detail,
        )
        operation = session.get(Operation, operation_id)
        if operation:
            operation.status = OperationStatus.failed
            operation.error = detail
            operation.completed_at = datetime.now(UTC)
        aggregate_model = {
            "signal": Signal,
            "bundle": Bundle,
        }.get(event.aggregate_type)
        aggregate_id = UUID(event.aggregate_id)
        aggregate = session.get(aggregate_model, aggregate_id) if aggregate_model else None
        if aggregate:
            aggregate.status = ProcessingStatus.failed

        # A bundle cannot become ready while one of its member signals is dead-lettered.
        # Project the child failure to every active parent so clients never see a
        # permanently-running operation and can explicitly retry the bundle.
        if event.aggregate_type == "signal":
            bundles = session.scalars(
                select(Bundle)
                .join(BundleItem, BundleItem.bundle_id == Bundle.id)
                .where(
                    BundleItem.signal_id == aggregate_id,
                    Bundle.archived_at.is_(None),
                )
            ).all()
            for bundle in bundles:
                bundle.status = ProcessingStatus.failed
                parent_detail = {**detail, "member_signal_id": event.aggregate_id}
                parent_operations = session.scalars(
                    select(Operation).where(
                        Operation.aggregate_type == "bundle",
                        Operation.aggregate_id == bundle.id,
                        Operation.status.in_((OperationStatus.pending, OperationStatus.running)),
                    )
                ).all()
                for parent_operation in parent_operations:
                    parent_operation.status = OperationStatus.failed
                    parent_operation.error = parent_detail
                    parent_operation.completed_at = datetime.now(UTC)


async def subscribe_role(js, role: str) -> None:
    async def callback(message):
        event = EventEnvelope.decode(message.data)
        consumer = f"{role}:{message.subject}"
        try:
            with session_scope() as session:
                if not claim_inbox(session, consumer, event):
                    await message.ack()
                    return
                processor = processor_for(role, message.subject)
                result = processor(session, event)
                if asyncio.iscoroutine(result):
                    await result
            await message.ack()
        except Exception as exc:
            delivered = getattr(getattr(message, "metadata", None), "num_delivered", 1)
            log.exception(
                "event.failed",
                role=role,
                subject=message.subject,
                event_id=event.event_id,
                delivered=delivered,
                error=str(exc),
            )
            if delivered >= settings.max_attempts:
                await mark_dead_letter(event, role, exc)
                await message.term()
            else:
                await message.nak(delay=min(2**delivered, 60))

    for index, subject in enumerate(SUBJECTS[role]):
        durable = f"stormcloud-{role}-{index}"
        await js.subscribe(
            subject,
            durable=durable,
            cb=callback,
            manual_ack=True,
            config=ConsumerConfig(
                durable_name=durable,
                ack_policy=AckPolicy.EXPLICIT,
                max_deliver=settings.max_attempts,
                ack_wait=180,
            ),
        )


async def run() -> None:
    configure_logging(settings.log_level)
    role = settings.worker_role
    if role not in SUBJECTS:
        raise ValueError(f"STORMCLOUD_WORKER_ROLE must be one of {sorted(SUBJECTS)}")
    connection = await nats.connect(
        settings.nats_url,
        name=f"stormcloud-{role}",
        reconnect_time_wait=2,
        max_reconnect_attempts=-1,
    )
    js = connection.jetstream()
    try:
        await js.add_stream(
            config=StreamConfig(
                name=settings.nats_stream,
                subjects=["stormcloud.>"],
                storage="file",
                duplicate_window=120,
            )
        )
    except Exception as exc:
        if (
            "stream name already in use" not in str(exc).lower()
            and "already in use" not in str(exc).lower()
        ):
            log.info("stream.exists_or_unavailable", detail=str(exc))
    await subscribe_role(js, role)
    tasks = []
    if role == "controller":
        tasks.append(asyncio.create_task(publish_outbox(js)))
    log.info("worker.ready", role=role, subjects=SUBJECTS[role])
    try:
        await asyncio.Event().wait()
    finally:
        for task in tasks:
            task.cancel()
        await connection.drain()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
