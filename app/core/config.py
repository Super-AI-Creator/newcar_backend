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
    sheets_auto_sync_enabled: bool = Field(False)
    sheets_auto_sync_interval_minutes: int = Field(10)
    sheets_auto_sync_run_on_startup: bool = Field(True)
    sheets_auto_sync_lock_wait_seconds: int = Field(20)
    sheets_webhook_secret: Optional[str] = Field(None)
    sheets_webhook_lock_wait_seconds: int = Field(2)
    lead_webhook_url: Optional[str] = Field(None)
    lead_webhook_secret: Optional[str] = Field(None)
    lead_webhook_timeout_seconds: int = Field(10)
    lead_webhook_max_attempts: int = Field(3)
    lead_webhook_retry_backoff_seconds: float = Field(1.0)
    credit_application_webhook_url: Optional[str] = Field(None)
    credit_application_webhook_secret: Optional[str] = Field(None)
    credit_application_webhook_timeout_seconds: int = Field(15)
    credit_application_webhook_max_attempts: int = Field(3)
    credit_application_webhook_retry_backoff_seconds: float = Field(1.0)
    credit_application_email_enabled: bool = Field(True)
    credit_application_notify_email: Optional[str] = Field(None)
    cloudinary_cloud_name: Optional[str] = Field(None)
    cloudinary_api_key: Optional[str] = Field(None)
    cloudinary_api_secret: Optional[str] = Field(None)
    cloudinary_upload_folder: str = Field("manual-vehicles")

    twilio_account_sid: Optional[str] = Field(None)
    twilio_auth_token: Optional[str] = Field(None)
    twilio_from_phone: Optional[str] = Field(None)
    frontend_base_url: str = Field("https://newcarsuperstore.com")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
