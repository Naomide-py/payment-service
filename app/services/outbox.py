import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Outbox


async def add_outbox_event(
    session: AsyncSession,
    *,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: dict,
) -> Outbox:
    event = Outbox(
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
    )
    session.add(event)
    return event
