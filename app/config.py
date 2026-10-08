from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    postgres_user: str = "payments"
    postgres_password: str = "payments"
    postgres_db: str = "payments"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # RabbitMQ
    rabbit_host: str = "rabbitmq"
    rabbit_port: int = 5672
    rabbit_user: str = "guest"
    rabbit_password: str = "guest"

    # API
    api_key: str = "secret-api-key"

    # Outbox publisher
    outbox_poll_interval: float = 1.0
    outbox_batch_size: int = 50

    # Consumer
    consumer_max_attempts: int = 3
    retry_base_delay: float = 1.0
    webhook_timeout: float = 10.0

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{quote(self.postgres_user, safe='')}:"
            f"{quote(self.postgres_password, safe='')}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def rabbit_url(self) -> str:
        return (
            f"amqp://{quote(self.rabbit_user, safe='')}:"
            f"{quote(self.rabbit_password, safe='')}"
            f"@{self.rabbit_host}:{self.rabbit_port}/"
        )


settings = Settings()
