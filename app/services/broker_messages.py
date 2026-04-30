from __future__ import annotations

BROKER_PREFIX = "[BROKER] "
CUSTOMER_PREFIX = "[CUSTOMER] "
CUSTOMER_CU_PREFIX = "[CUSTOMER_CU] "
CUSTOMER_BROKER_PREFIX = "[CUSTOMER_BROKER] "
CREDIT_UNION_PREFIX = "[CREDIT_UNION] "


def map_member_audience_to_sender_type(audience: str) -> str:
    """Member-authored rows: both threads, CU-only, or dealer-only."""
    a = (audience or "both").strip().lower()
    if a == "cu":
        return "customer_cu"
    if a == "broker":
        return "customer_broker"
    return "customer"


def should_sync_customer_message_to_ghl(sender_type: str) -> bool:
    """CU-only member lines skip GHL deal-room inbound."""
    return sender_type in ("customer", "customer_broker")


def should_run_broker_customer_webhook(sender_type: str) -> bool:
    """Make/Zapier dealer webhook for shared or dealer-only member messages."""
    return sender_type in ("customer", "customer_broker")


def encode_message_for_storage(message_text: str, sender_type: str) -> str:
    clean = (message_text or "").strip()
    st = (sender_type or "customer").strip().lower()
    if st == "broker":
        return f"{BROKER_PREFIX}{clean}"
    if st == "credit_union":
        return f"{CREDIT_UNION_PREFIX}{clean}"
    if st == "customer_cu":
        return f"{CUSTOMER_CU_PREFIX}{clean}"
    if st == "customer_broker":
        return f"{CUSTOMER_BROKER_PREFIX}{clean}"
    return f"{CUSTOMER_PREFIX}{clean}"


def parse_message_from_storage(raw_text: str) -> tuple[str, str]:
    text = raw_text or ""
    if text.startswith(BROKER_PREFIX):
        return ("broker", text[len(BROKER_PREFIX) :].strip())
    if text.startswith(CREDIT_UNION_PREFIX):
        return ("credit_union", text[len(CREDIT_UNION_PREFIX) :].strip())
    if text.startswith(CUSTOMER_CU_PREFIX):
        return ("customer_cu", text[len(CUSTOMER_CU_PREFIX) :].strip())
    if text.startswith(CUSTOMER_BROKER_PREFIX):
        return ("customer_broker", text[len(CUSTOMER_BROKER_PREFIX) :].strip())
    if text.startswith(CUSTOMER_PREFIX):
        return ("customer", text[len(CUSTOMER_PREFIX) :].strip())
    return ("customer", text.strip())
