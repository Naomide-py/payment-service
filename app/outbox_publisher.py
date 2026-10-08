import asyncio
import logging
from datetime import datetime, timezone

from faststream.rabbit import RabbitBroker
from sqlalchemy import select

from app.broker.topology import (
    PAYMENTS_EXCHANGE,
    PAYMENTS_ROUTING_KEY,
    declare_topology,
)
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Outbox

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbox-publisher")

broker = RabbitBroker(settings.rabbit_url)


async def publish_once() -> int:
    published = 0
    async with AsyncSessionLocal() as session:
        events = (
            await session.scalars(
                select(Outbox)
                .where(Outbox.published_at.is_(None))
                .order_by(Outbox.created_at)
                .limit(settings.outbox_batch_size)
                .with_for_update(skip_locked=True)
            )
        ).all()

        for event in events:
            try:
                await broker.publish(
                    {
                        "event_id": str(event.id),
                        "event_type": event.event_type,
                        "aggregate_id": str(event.aggregate_id),
                        "payload": event.payload,
                    },
                    exchange=PAYMENTS_EXCHANGE,
                    routing_key=PAYMENTS_ROUTING_KEY,
                    persist=True,
                    message_id=str(event.id),
                )
            except Exception:
                logger.exception("Failed to publish outbox event %s", event.id)
                break

            event.published_at = datetime.now(timezone.utc)
            published += 1

        await session.commit()

    return published


async def main() -> None:
    await broker.start()
    await declare_topology(broker)
    logger.info("Outbox publisher started")
    try:
        while True:
            try:
                count = await publish_once()
                if count == 0:
                    await asyncio.sleep(settings.outbox_poll_interval)
            except Exception:
                logger.exception("Outbox publisher iteration failed")
                await asyncio.sleep(settings.outbox_poll_interval)
    finally:
        await broker.close()


if __name__ == "__main__":
    asyncio.run(main())
