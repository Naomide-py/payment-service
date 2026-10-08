import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Payment, PaymentStatus
from app.schemas import PaymentCreate
from app.services.outbox import add_outbox_event


class IdempotencyConflict(Exception):
    pass


async def _find_by_key(session: AsyncSession, key: str) -> Payment | None:
    return await session.scalar(
        select(Payment).where(Payment.idempotency_key == key)
    )


def _same_request(payment: Payment, data: PaymentCreate) -> bool:
    return (
        payment.amount == data.amount
        and payment.currency == data.currency
        and payment.description == data.description
        and payment.meta == data.meta
        and payment.webhook_url == str(data.webhook_url)
    )


def _replay(payment: Payment, data: PaymentCreate) -> Payment:
    if not _same_request(payment, data):
        raise IdempotencyConflict()
    return payment


async def create_payment(
    session: AsyncSession,
    *,
    idempotency_key: str,
    data: PaymentCreate,
) -> Payment:
    existing = await _find_by_key(session, idempotency_key)
    if existing is not None:
        return _replay(existing, data)

    payment = Payment(
        amount=data.amount,
        currency=data.currency,
        description=data.description,
        meta=data.meta,
        status=PaymentStatus.pending,
        idempotency_key=idempotency_key,
        webhook_url=str(data.webhook_url),
    )
    session.add(payment)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await _find_by_key(session, idempotency_key)
        if existing is None:
            raise
        return _replay(existing, data)

    await add_outbox_event(
        session,
        aggregate_id=payment.id,
        event_type="payment.created",
        payload={"payment_id": str(payment.id)},
    )
    await session.commit()
    await session.refresh(payment)
    return payment


async def get_payment(session: AsyncSession, payment_id: uuid.UUID) -> Payment | None:
    return await session.get(Payment, payment_id)
