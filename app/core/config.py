from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NewCarSuperstore App Backend"
    environment: str = "local"

    mysql_host: str = Field(...)
    mysql_port: int = Field(3306)
    mysql_user: str = Field(...)
    mysql_password: str = Field(...)
    mysql_db: str = Field(...)

    jwt_secret: str = Field(...)
    jwt_algorithm: str = Field("HS256")
    jwt_access_token_minutes: int = Field(60 * 24)
    jwt_refresh_token_days: int = Field(30)

    google_client_id: str = Field(...)
    google_service_account_json: Optional[str] = Field(None)

    smtp_host: str = Field(...)
    smtp_port: int = Field(587)
    smtp_username: str = Field(...)
    smtp_password: str = Field(...)
    smtp_use_tls: bool = Field(True)
    smtp_from_email: str = Field(...)
    broker_email: str = Field(...)
    email_provider: str = Field("auto")
    resend_api_key: Optional[str] = Field(None)
    resend_from_email: Optional[str] = Field(None)

    offers_sheet_id: Optional[str] = Field(None)
    offers_sheet_tab: Optional[str] = Field(None)
    scores_sheet_id: Optional[str] = Field(None)
    scores_sheet_tab: Optional[str] = Field(None)

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
