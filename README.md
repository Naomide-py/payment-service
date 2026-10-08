# Payment Processing Service

Асинхронный микросервис процессинга платежей:
FastAPI + Pydantic v2 + SQLAlchemy 2.0 (async) + PostgreSQL + RabbitMQ (FastStream) + Alembic.

## Архитектура

```
Client ──► API ──► PostgreSQL (payments + outbox, одна транзакция)
                     ▲
                     │ poll (FOR UPDATE SKIP LOCKED)
              Outbox Publisher ──► RabbitMQ: exchange payments ──► queue payments.new
                                                                       │
                                                                       ▼
                                                                   Consumer
                                                     (шлюз-эмуляция → статус в БД → webhook)
                                                                       │
                                                  3 попытки (1s, 2s) ──┴─► reject
                                                                            ▼
                                                      payments.dlx ──► payments.dlq
```

Процессы: `api`, `outbox-publisher`, `consumer`, одноразовый `migrate`.

## Запуск

```bash
cp .env.example .env     # опционально: значения по умолчанию совпадают
docker compose up --build
```

- API / Swagger: http://localhost:8000/docs
- RabbitMQ Management: http://localhost:15672 (guest / guest)
- PostgreSQL: localhost:5432

## Примеры

### Создание платежа

```bash
curl -X POST http://localhost:8000/api/v1/payments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret-api-key" \
  -H "Idempotency-Key: order-12345" \
  -d '{
    "amount": "100.50",
    "currency": "USD",
    "description": "Test payment",
    "meta": {"order_id": "12345"},
    "webhook_url": "https://webhook.site/your-uuid"
  }'
```

Ответ `202 Accepted`:

```json
{
  "payment_id": "6b1f...",
  "status": "pending",
  "created_at": "2024-01-01T12:00:00Z"
}
```

### Получение платежа

```bash
curl http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: secret-api-key"
```

### Коды ответов

| Код | Когда |
|-----|-------|
| 202 | платёж принят (в том числе идемпотентный повтор) |
| 400 | пустой или слишком длинный `Idempotency-Key` |
| 401 | нет или неверный `X-API-Key` |
| 404 | платёж не найден |
| 409 | `Idempotency-Key` уже использован с другими параметрами |
| 422 | ошибка валидации тела / заголовков |

### Формат webhook

`POST <webhook_url>`:

```json
{
  "payment_id": "6b1f...",
  "status": "succeeded",
  "amount": "100.50",
  "currency": "USD",
  "processed_at": "2024-01-01T12:00:04+00:00"
}
```

Успешной доставкой считается ответ 2xx.

## Гарантии доставки

- **Outbox** — событие пишется в БД в одной транзакции с платежом и публикуется
  фоновым воркером с подтверждением брокера (publisher confirms). Событие помечается
  опубликованным только после подтверждения → доставка *at-least-once*.
- **Idempotency-Key** — повтор с теми же параметрами возвращает тот же `payment_id`;
  с другими параметрами — `409`. Гонка параллельных запросов обрабатывается через
  уникальный индекс.
- **Идемпотентный consumer** — статус меняется атомарным `UPDATE ... WHERE status='pending'`,
  дубли сообщений безопасны. Доставка webhook отслеживается отдельным полем
  `webhook_delivered_at`, поэтому сбой между сменой статуса и отправкой webhook
  не приводит к потере уведомления: при повторной доставке сообщения webhook будет
  отправлен.
- **Retry** — вся обработка сообщения выполняется до 3 попыток с экспоненциальной
  задержкой между ними (1s, 2s; настраивается `RETRY_BASE_DELAY`).
- **DLQ** — после 3 неудачных попыток сообщение отклоняется (`reject`, без requeue)
  и через `payments.dlx` попадает в `payments.dlq`. Статус платежа при этом уже
  сохранён в БД, `webhook_delivered_at` остаётся `NULL`.

## Переменные окружения

См. `.env.example`. Дополнительно (необязательные): `OUTBOX_POLL_INTERVAL`,
`OUTBOX_BATCH_SIZE`, `CONSUMER_MAX_ATTEMPTS`, `RETRY_BASE_DELAY`, `WEBHOOK_TIMEOUT`.

## Миграции

Применяются автоматически сервисом `migrate`. Вручную:

```bash
docker compose run --rm migrate alembic upgrade head
```

## Допущения и ограничения

- `webhook_url` принимается как есть (только http/https). В production нужна защита
  от SSRF: запрет внутренних адресов, allow-list доменов, подпись webhook.
- Один API-ключ статически задаётся в окружении.
