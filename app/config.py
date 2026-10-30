from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True
    )

    PROJECT_NAME: str = "Pocket Mechanic API"
    API_V1_STR: str = "/api/v1"

    NINEROUTER_API_KEY: str = Field("", env="NINEROUTER_API_KEY")
    NINEROUTER_BASE_URL: str = Field(
        "https://9router.hariinidev.tech/v1", env="NINEROUTER_BASE_URL"
    )
    NINEROUTER_MODEL: str = Field("gemini/gemini-3.6-flash", env="NINEROUTER_MODEL")
    NINEROUTER_TIMEOUT: float = Field(150.0, env="NINEROUTER_TIMEOUT")

    DATABASE_URL: str = Field(..., env="DATABASE_URL")

    SECRET_KEY: str = Field(..., env="SECRET_KEY")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7


settings = Settings()
