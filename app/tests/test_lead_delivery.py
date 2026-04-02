from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.models.lead_request import LeadRequest
from app.services import lead_delivery


class _OkResponse:
    def raise_for_status(self):
        return None


def _set_lead_webhook_settings(
    *,
    url=None,
    secret=None,
    timeout=10,
    attempts=3,
    backoff=0.0,
):
    settings.lead_webhook_url = url
    settings.lead_webhook_secret = secret
    settings.lead_webhook_timeout_seconds = timeout
    settings.lead_webhook_max_attempts = attempts
    settings.lead_webhook_retry_backoff_seconds = backoff


def test_build_lead_webhook_payload_includes_expected_fields():
    created_at = datetime(2026, 3, 9, 18, 20, tzinfo=timezone.utc)
    row = LeadRequest(
        id=10,
        name="John Doe",
        email="john@example.com",
        phone="+13105551212",
        vin="1HGCM82633A004352",
        year=2024,
        make="Toyota",
        model="Camry",
        trim="SE",
        vehicle="2024 Toyota Camry SE",
        source="newcarsuperstore.com",
        notes="Needs lease options",
        created_at=created_at,
    )

    payload = lead_delivery.build_lead_webhook_payload(row)

    assert payload["lead_id"] == 10
    assert payload["created_at"] == created_at.isoformat()
    assert payload["email"] == "john@example.com"
    assert payload["vehicle"] == "2024 Toyota Camry SE"


def test_send_lead_webhook_retries_then_succeeds(monkeypatch):
    prior = (
        settings.lead_webhook_url,
        settings.lead_webhook_secret,
        settings.lead_webhook_timeout_seconds,
        settings.lead_webhook_max_attempts,
        settings.lead_webhook_retry_backoff_seconds,
    )
    _set_lead_webhook_settings(
        url="https://hook.example.test/lead",
        secret="abc123",
        timeout=3,
        attempts=3,
        backoff=0.0,
    )

    calls = []

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None, headers=None):
            calls.append((url, json, headers))
            if len(calls) < 3:
                raise httpx.ConnectError("network issue", request=httpx.Request("POST", url))
            return _OkResponse()

    monkeypatch.setattr(lead_delivery.httpx, "Client", _FakeClient)
    monkeypatch.setattr(lead_delivery, "_update_lead_delivery_state", lambda *args, **kwargs: None)

    try:
        lead_delivery.send_lead_webhook({"lead_id": 99, "email": "john@example.com"})
    finally:
        (
            settings.lead_webhook_url,
            settings.lead_webhook_secret,
            settings.lead_webhook_timeout_seconds,
            settings.lead_webhook_max_attempts,
            settings.lead_webhook_retry_backoff_seconds,
        ) = prior

    assert len(calls) == 3
    assert calls[0][2]["X-Webhook-Secret"] == "abc123"


def test_process_new_lead_integrations_skips_webhook_when_ghl_contact_exists(monkeypatch):
    prior_url = settings.lead_webhook_url
    settings.lead_webhook_url = "https://hook.example.test/lead"
    webhook_calls = []
    state_updates = []

    monkeypatch.setattr(
        lead_delivery,
        "lookup_ghl_contact_for_credit_payload",
        lambda _p: ("contact-ghl-1", "found"),
    )
    monkeypatch.setattr(
        lead_delivery,
        "create_ghl_contact_for_lead",
        lambda _p: ("contact-ghl-1", "found"),
    )
    monkeypatch.setattr(
        lead_delivery,
        "send_lead_webhook",
        lambda p: webhook_calls.append(p),
    )
    monkeypatch.setattr(
        lead_delivery,
        "_update_lead_delivery_state",
        lambda *args, **kwargs: state_updates.append((args, kwargs)),
    )

    try:
        lead_delivery.process_new_lead_integrations({"lead_id": 5, "email": "a@b.com", "phone": "3105551212"})
    finally:
        settings.lead_webhook_url = prior_url

    assert webhook_calls == []
    assert any(
        kwargs.get("webhook_status") == "skipped"
        and "GoHighLevel" in (kwargs.get("webhook_last_error") or "")
        for _a, kwargs in state_updates
    )


def test_process_new_lead_integrations_sends_webhook_when_contact_not_in_ghl(monkeypatch):
    prior_url = settings.lead_webhook_url
    settings.lead_webhook_url = "https://hook.example.test/lead"
    webhook_calls = []

    monkeypatch.setattr(
        lead_delivery,
        "lookup_ghl_contact_for_credit_payload",
        lambda _p: (None, "not_found"),
    )
    monkeypatch.setattr(
        lead_delivery,
        "create_ghl_contact_for_lead",
        lambda _p: ("new-id", "found"),
    )
    monkeypatch.setattr(
        lead_delivery,
        "send_lead_webhook",
        lambda p: webhook_calls.append(p),
    )
    monkeypatch.setattr(lead_delivery, "_update_lead_delivery_state", lambda *args, **kwargs: None)

    try:
        lead_delivery.process_new_lead_integrations({"lead_id": 7, "email": "new@b.com", "phone": "3105559999"})
    finally:
        settings.lead_webhook_url = prior_url

    assert len(webhook_calls) == 1
    assert webhook_calls[0]["lead_id"] == 7
