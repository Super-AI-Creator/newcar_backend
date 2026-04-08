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
    # In serverless (Vercel/Lambda), background threads are not reliable and can create lock noise.
    # Keep disabled by default unless explicitly enabled.
    sheets_auto_sync_allow_serverless: bool = Field(False)
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
    # Deal Room: customer → broker chat → Make.com → GoHighLevel (optional webhook URL)
    broker_message_webhook_url: Optional[str] = Field(None)
    broker_message_webhook_secret: Optional[str] = Field(None)
    broker_message_webhook_timeout_seconds: int = Field(15)
    broker_message_webhook_max_attempts: int = Field(3)
    broker_message_webhook_retry_backoff_seconds: float = Field(1.0)
    credit_application_email_enabled: bool = Field(True)
    credit_application_notify_email: Optional[str] = Field(None)
    # GoHighLevel Lead Connector API (optional): used to detect existing contacts and email fallback when none.
    ghl_private_integration_token: Optional[str] = Field(None)
    # Optional second PIT with conversations/message.write only; inbound Deal Room messages use this if set.
    ghl_conversations_private_integration_token: Optional[str] = Field(None)
    ghl_location_id: Optional[str] = Field(None)
    # When true (default), customer Deal Room messages sync to GHL inbound conversation if contact exists (by email).
    ghl_deal_room_conversation_enabled: bool = Field(True)
    credit_application_ghl_fallback_email: Optional[str] = Field(None)
    cloudinary_cloud_name: Optional[str] = Field(None)
    cloudinary_api_key: Optional[str] = Field(None)
    cloudinary_api_secret: Optional[str] = Field(None)
    cloudinary_upload_folder: str = Field("manual-vehicles")

    twilio_account_sid: Optional[str] = Field(None)
    twilio_auth_token: Optional[str] = Field(None)
    twilio_from_phone: Optional[str] = Field(None)
    frontend_base_url: str = Field("https://newcarsuperstore.com")
    # Optional comma-separated CORS origins for manage_backend.
    cors_origins: Optional[str] = Field(None)
    # Optional comma-separated list of extra origins for the standalone CU API.
    # Parsed by credit_union_platform/backend/main.py.
    cu_cors_origins: Optional[str] = Field(None)
    # When set, CU approval letter / SMS claim links and white-label portal URLs use this base
    # (standalone credit union web app) instead of frontend_base_url.
    cu_portal_base_url: Optional[str] = Field(None)
    # Marketing demo form on CU landing: notify this address (default chris@carscu.com).
    cu_demo_contact_notify_email: str = Field("chris@carscu.com")
    # Per client IP (or X-Forwarded-For) sliding-window cap for POST /public/cu-demo-contact.
    cu_demo_contact_rate_limit_per_minute: int = Field(8, ge=1, le=120)
    # When set, member/broker deal-room messages assign to this broker_admin user only (e.g. Power Auto Buying).
    broker_single_assign_email: Optional[str] = Field(None)

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
