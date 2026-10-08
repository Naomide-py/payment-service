from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

PAYMENTS_ROUTING_KEY = "payments.new"
DLQ_ROUTING_KEY = "payments.dlq"

PAYMENTS_EXCHANGE = RabbitExchange(
    "payments", type=ExchangeType.DIRECT, durable=True
)
DLX_EXCHANGE = RabbitExchange(
    "payments.dlx", type=ExchangeType.DIRECT, durable=True
)

PAYMENTS_NEW_QUEUE = RabbitQueue(
    "payments.new",
    durable=True,
    routing_key=PAYMENTS_ROUTING_KEY,
    arguments={
        "x-dead-letter-exchange": DLX_EXCHANGE.name,
        "x-dead-letter-routing-key": DLQ_ROUTING_KEY,
    },
)
PAYMENTS_DLQ = RabbitQueue(
    "payments.dlq", durable=True, routing_key=DLQ_ROUTING_KEY
)


async def declare_topology(broker: RabbitBroker) -> None:
    dlx = await broker.declare_exchange(DLX_EXCHANGE)
    dlq = await broker.declare_queue(PAYMENTS_DLQ)
    await dlq.bind(dlx, routing_key=DLQ_ROUTING_KEY)

    exchange = await broker.declare_exchange(PAYMENTS_EXCHANGE)
    queue = await broker.declare_queue(PAYMENTS_NEW_QUEUE)
    await queue.bind(exchange, routing_key=PAYMENTS_ROUTING_KEY)
