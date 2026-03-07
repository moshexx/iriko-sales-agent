from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = "development"
    app_secret_key: str = "change-me"
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://leadwise:leadwise@localhost:5432/leadwise"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # LLM
    default_llm_model: str = "anthropic/claude-sonnet-4-6"
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Green API
    green_api_instance_id: str = ""
    green_api_token: str = ""

    # Observability
    otel_exporter_otlp_endpoint: str = "https://signoz.simpliflow.me:4317"
    otel_service_name: str = "leadwise-sales-agent"
    otel_enabled: bool = False

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
