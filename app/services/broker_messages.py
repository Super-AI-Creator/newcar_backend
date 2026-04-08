from __future__ import annotations

BROKER_PREFIX = "[BROKER] "
CUSTOMER_PREFIX = "[CUSTOMER] "
CREDIT_UNION_PREFIX = "[CREDIT_UNION] "


def encode_message_for_storage(message_text: str, sender_type: str) -> str:
    clean = (message_text or "").strip()
    if sender_type == "broker":
        return f"{BROKER_PREFIX}{clean}"
    if sender_type == "credit_union":
        return f"{CREDIT_UNION_PREFIX}{clean}"
    return f"{CUSTOMER_PREFIX}{clean}"


def parse_message_from_storage(raw_text: str) -> tuple[str, str]:
    text = raw_text or ""
    if text.startswith(BROKER_PREFIX):
        return ("broker", text[len(BROKER_PREFIX) :].strip())
    if text.startswith(CREDIT_UNION_PREFIX):
        return ("credit_union", text[len(CREDIT_UNION_PREFIX) :].strip())
    if text.startswith(CUSTOMER_PREFIX):
        return ("customer", text[len(CUSTOMER_PREFIX) :].strip())
    return ("customer", text.strip())
