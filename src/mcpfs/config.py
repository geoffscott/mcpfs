from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCPFS_", env_file=None, extra="ignore")

    bucket: str = Field(..., description="GCS bucket holding all objects.")
    max_object_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=512 * 1024 * 1024)
    list_page_size: int = Field(default=1000, ge=1, le=10000)
    require_identity_header: bool = Field(
        default=True,
        description="Refuse requests lacking a Cloud Run-authenticated identity header.",
    )
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: str = Field(default="INFO")


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
