import asyncio
import logging
import random
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TypeVar

import httpx
from faststream import FastStream
from faststream.rabbit import RabbitBroker
from faststream.rabbit.annotations import RabbitMessage
from pydantic import BaseModel
from sqlalchemy import update

from app.broker.topology import (
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_QUEUE,
    declare_topology,
)
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Payment, PaymentStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("consumer")

broker = RabbitBroker(settings.rabbit_url)
app = FastStream(broker)

T = TypeVar("T")


class PaymentEvent(BaseModel):
    event_id: str
    event_type: str
    aggregate_id: str
    payload: dict


class PaymentNotFound(Exception):
    pass


class WebhookDeliveryError(Exception):
    pass


async def with_retries(
    func: Callable[[], Awaitable[T]], *, attempts: int, base_delay: float
) -> T:
    delay = base_delay
    for attempt in range(1, attempts + 1):
        try:
            return await func()
        except Exception as exc:
            if attempt == attempts:
                raise
            logger.warning(
                "Attempt %d/%d failed (%s: %s); retry in %.1fs",
                attempt,
                attempts,
                type(exc).__name__,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


async def emulate_gateway() -> bool:
    await asyncio.sleep(random.uniform(2, 5))
    return random.random() < 0.9


async def send_webhook(url: str, payload: dict) -> bool:
    try:
        async with httpx.AsyncClient(timeout=settings.webhook_timeout) as client:
            response = await client.post(url, json=payload)
        if 200 <= response.status_code < 300:
            return True
        logger.warning("Webhook %s returned status %s", url, response.status_code)
    except Exception as exc:
        logger.warning("Webhook %s request failed: %s", url, exc)
    return False


async def _load_payment(payment_id: uuid.UUID) -> Payment:
    async with AsyncSessionLocal() as session:
        payment = await session.get(Payment, payment_id)
    if payment is None:
        raise PaymentNotFound(str(payment_id))
    return payment


async def _finalize_payment(payment_id: uuid.UUID, success: bool) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Payment)
            .where(Payment.id == payment_id, Payment.status == PaymentStatus.pending)
            .values(
                status=PaymentStatus.succeeded if success else PaymentStatus.failed,
                processed_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


async def _mark_webhook_delivered(payment_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Payment)
            .where(Payment.id == payment_id)
            .values(webhook_delivered_at=datetime.now(timezone.utc))
        )
        await session.commit()


async def process_payment(payment_id: uuid.UUID) -> None:
    payment = await _load_payment(payment_id)

    if payment.status == PaymentStatus.pending:
        success = await emulate_gateway()
        await _finalize_payment(payment_id, success)
        payment = await _load_payment(payment_id)

    if payment.webhook_delivered_at is not None:
        logger.info("Payment %s: webhook already delivered", payment_id)
        return

    webhook_payload = {
        "payment_id": str(payment.id),
        "status": payment.status.value,
        "amount": str(payment.amount),
        "currency": payment.currency.value,
        "processed_at": payment.processed_at.isoformat()
        if payment.processed_at
        else None,
    }
    if not await send_webhook(payment.webhook_url, webhook_payload):
        raise WebhookDeliveryError(f"webhook failed for payment {payment_id}")

    await _mark_webhook_delivered(payment_id)
    logger.info("Payment %s: webhook delivered", payment_id)


@broker.subscriber(PAYMENTS_NEW_QUEUE, PAYMENTS_EXCHANGE)
async def handle_payment_created(event: PaymentEvent, message: RabbitMessage) -> None:
    payment_id = uuid.UUID(event.payload.get("payment_id") or event.aggregate_id)
    try:
        await with_retries(
            lambda: process_payment(payment_id),
            attempts=settings.consumer_max_attempts,
            base_delay=settings.retry_base_delay,
        )
    except Exception:
        logger.exception(
            "Payment %s failed after %d attempts -> DLQ",
            payment_id,
            settings.consumer_max_attempts,
        )
        await message.reject()


@app.after_startup
async def setup_topology() -> None:
    await declare_topology(broker)


if __name__ == "__main__":
    asyncio.run(app.run())
