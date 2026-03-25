"""Human-readable plain text and HTML summaries for credit applications (email, CRM, admin)."""

from __future__ import annotations

import html
from typing import Any, Mapping, Optional

EMPLOYMENT_LABELS = {
    "employed": "I am Employed",
    "unemployed": "I am Unemployed",
    "retired": "Retired",
}

HOUSING_LABELS = {
    "rent": "I rent",
    "own": "I own my house",
}


def _s(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        if v != v:  # NaN
            return ""
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return str(v).strip()


def _mask_ssn(raw: Optional[str]) -> str:
    if not raw or not str(raw).strip():
        return "—"
    digits = "".join(c for c in str(raw) if c.isdigit())
    if len(digits) >= 4:
        return f"***-**-{digits[-4:]}"
    return "••••••••"


def _mask_dl(raw: Optional[str]) -> str:
    if not raw or not str(raw).strip():
        return "—"
    s = str(raw).strip()
    if len(s) <= 3:
        return "•••"
    return f"••••••{s[-3:]}"


def _employment_label(key: Optional[str]) -> str:
    if not key:
        return "—"
    return EMPLOYMENT_LABELS.get(key.strip().lower(), _s(key))


def _housing_label(key: Optional[str]) -> str:
    if not key:
        return "—"
    return HOUSING_LABELS.get(key.strip().lower(), _s(key))


def _format_money(v: Any) -> str:
    if v is None or v == "":
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return _s(v)
    return f"${n:,.2f}"


def _line(label: str, value: str, width: int = 28) -> str:
    val = value if value else "—"
    return f"{label.ljust(width)}{val}"


def _join_address(
    street: Optional[str],
    city: Optional[str],
    state: Optional[str],
    zip_code: Optional[str],
) -> str:
    parts = [_s(street), _s(city)]
    tail = " ".join(p for p in [_s(state), _s(zip_code)] if p).strip()
    if tail:
        parts.append(tail)
    return ", ".join(p for p in parts if p) or "—"


def _vehicle_line(p: Mapping[str, Any]) -> str:
    parts = [
        _s(p.get("vehicle_make")),
        _s(p.get("vehicle_model")),
        _s(p.get("vehicle_trim")),
    ]
    text = " ".join(x for x in parts if x).strip()
    vin = _s(p.get("vin"))
    if vin and text:
        return f"{text} (VIN {vin})"
    if vin:
        return f"VIN {vin}"
    return text or "—"


def format_credit_application_plain(p: Mapping[str, Any], *, mask_sensitive: bool = True) -> str:
    """Fixed-width style plain text, similar to legacy credit application emails."""

    def sens(key: str) -> str:
        v = p.get(key)
        if mask_sensitive:
            if key == "ssn":
                return _mask_ssn(v if isinstance(v, str) else None)
            if key == "drivers_license_number":
                return _mask_dl(v if isinstance(v, str) else None)
        return _s(v) or "—"

    lines: list[str] = [
        "",
        "CREDIT APPLICATION",
        "=" * 56,
        "",
        "Personal Info (required)",
        "-" * 56,
        _line("First Name:", _s(p.get("first_name"))),
        _line("Last Name:", _s(p.get("last_name"))),
        _line("Email:", _s(p.get("email"))),
        _line("Birth Date:", _s(p.get("birth_date"))),
        _line("Social Security Number:", sens("ssn")),
        _line("Drivers License Number:", sens("drivers_license_number")),
        "",
        "Current Address Info (required)",
        "-" * 56,
        _line("Current Address:", _join_address(p.get("street_address"), p.get("city"), p.get("state"), p.get("zip_code"))),
        _line("How long at current address:", _s(p.get("time_at_current_address"))),
        _line("Phone:", _s(p.get("home_phone"))),
        "",
        "Previous Address Info (optional if at current > 3 years)",
        "-" * 56,
        _line(
            "Previous Address:",
            _join_address(
                p.get("previous_street_address"),
                p.get("previous_city"),
                p.get("previous_state"),
                p.get("previous_zip_code"),
            ),
        ),
        _line("How long at this address:", _s(p.get("time_at_previous_address"))),
        "",
        "Current Employment Info",
        "-" * 56,
        _line("Employment Status:", _employment_label(p.get("employment_status") if isinstance(p.get("employment_status"), str) else None)),
        _line("Occupation title:", _s(p.get("occupation_title"))),
        _line("Present employer:", _s(p.get("employer_name"))),
        _line("Work phone number:", _s(p.get("work_phone"))),
        _line("How long:", _s(p.get("time_at_current_job"))),
        _line(
            "Work Address:",
            _join_address(
                p.get("work_street_address"),
                p.get("work_city"),
                p.get("work_state"),
                p.get("work_zip_code"),
            ),
        ),
        "",
        "Previous Employment Info",
        "-" * 56,
        _line("Previous Employer (to cover 5 years):", _s(p.get("previous_employer"))),
        _line("How long previous:", _s(p.get("time_at_previous_employer"))),
        "",
        "Income Info",
        "-" * 56,
        _line("Monthly Income:", _format_money(p.get("gross_monthly_income"))),
        _line("Do you rent or own:", _housing_label(p.get("housing_status") if isinstance(p.get("housing_status"), str) else None)),
        _line("Monthly Payment or Rent:", _format_money(p.get("monthly_housing_payment"))),
        _line("Salesperson Name:", _s(p.get("salesperson_name"))),
        _line("Electronic Signature:", _s(p.get("electronic_signature"))),
        _line("Consent (terms of service):", "Yes" if p.get("agreed_to_terms") else "No"),
        "",
        "Vehicle / notes",
        "-" * 56,
        _line("Vehicle:", _vehicle_line(p)),
        _line("Notes:", _s(p.get("notes"))),
        "",
        "=" * 56,
    ]
    return "\n".join(lines).strip() + "\n"


def _row_html(label: str, value: str) -> str:
    v = html.escape(value if value else "—")
    return (
        f'<tr><td style="padding:6px 12px;border:1px solid #ddd;background:#f9f9f9;'
        f'font-weight:600;width:38%;vertical-align:top;">{html.escape(label)}</td>'
        f'<td style="padding:6px 12px;border:1px solid #ddd;vertical-align:top;">{v}</td></tr>'
    )


def _section_html(title: str, rows: list[tuple[str, str]]) -> str:
    body = "".join(_row_html(lab, val) for lab, val in rows)
    return (
        f'<div style="margin:16px 0 8px 0;background:#333;color:#fff;padding:10px 14px;'
        f'font-family:system-ui,Segoe UI,sans-serif;font-size:14px;font-weight:600;">{html.escape(title)}</div>'
        f'<table style="width:100%;border-collapse:collapse;font-family:system-ui,Segoe UI,sans-serif;font-size:14px;">{body}</table>'
    )


def format_credit_application_html(p: Mapping[str, Any], *, mask_sensitive: bool = True) -> str:
    def sens(key: str) -> str:
        v = p.get(key)
        if mask_sensitive:
            if key == "ssn":
                return _mask_ssn(v if isinstance(v, str) else None)
            if key == "drivers_license_number":
                return _mask_dl(v if isinstance(v, str) else None)
        return _s(v) or "—"

    parts: list[str] = [
        '<div style="font-family:system-ui,Segoe UI,sans-serif;color:#111;max-width:720px;">',
        '<h1 style="text-align:center;margin:0 0 16px;font-size:22px;">Credit Application</h1>',
    ]

    parts.append(
        _section_html(
            "Personal Info (required)",
            [
                ("First Name", _s(p.get("first_name"))),
                ("Last Name", _s(p.get("last_name"))),
                ("Email", _s(p.get("email"))),
                ("Birth Date", _s(p.get("birth_date"))),
                ("Social Security Number", sens("ssn")),
                ("Drivers License Number", sens("drivers_license_number")),
            ],
        )
    )
    parts.append(
        _section_html(
            "Current Address Info (required)",
            [
                (
                    "Current Address",
                    _join_address(p.get("street_address"), p.get("city"), p.get("state"), p.get("zip_code")),
                ),
                ("How long at current address", _s(p.get("time_at_current_address"))),
                ("Phone", _s(p.get("home_phone"))),
            ],
        )
    )
    parts.append(
        _section_html(
            "Previous Address Info (optional)",
            [
                (
                    "Previous Address",
                    _join_address(
                        p.get("previous_street_address"),
                        p.get("previous_city"),
                        p.get("previous_state"),
                        p.get("previous_zip_code"),
                    ),
                ),
                ("How long at this address", _s(p.get("time_at_previous_address"))),
            ],
        )
    )
    parts.append(
        _section_html(
            "Current Employment Info",
            [
                ("Employment Status", _employment_label(p.get("employment_status") if isinstance(p.get("employment_status"), str) else None)),
                ("Occupation title", _s(p.get("occupation_title"))),
                ("Present employer", _s(p.get("employer_name"))),
                ("Work phone number", _s(p.get("work_phone"))),
                ("How long", _s(p.get("time_at_current_job"))),
                (
                    "Work Address",
                    _join_address(
                        p.get("work_street_address"),
                        p.get("work_city"),
                        p.get("work_state"),
                        p.get("work_zip_code"),
                    ),
                ),
            ],
        )
    )
    parts.append(
        _section_html(
            "Previous Employment Info",
            [
                ("Previous Employer (to cover 5 years)", _s(p.get("previous_employer"))),
                ("How long previous", _s(p.get("time_at_previous_employer"))),
            ],
        )
    )
    parts.append(
        _section_html(
            "Income Info",
            [
                ("Monthly Income", _format_money(p.get("gross_monthly_income"))),
                ("Do you rent or own", _housing_label(p.get("housing_status") if isinstance(p.get("housing_status"), str) else None)),
                ("Monthly Payment or Rent", _format_money(p.get("monthly_housing_payment"))),
                ("Salesperson Name", _s(p.get("salesperson_name"))),
                ("Electronic Signature", _s(p.get("electronic_signature"))),
                ("Consent (terms of service)", "Yes" if p.get("agreed_to_terms") else "No"),
            ],
        )
    )
    parts.append(
        _section_html(
            "Vehicle / notes",
            [
                ("Vehicle", _vehicle_line(p)),
                ("Notes", _s(p.get("notes"))),
            ],
        )
    )
    parts.append("</div>")
    return "".join(parts)


def enrich_payload_with_formatted(payload: dict, *, mask_sensitive: bool = True) -> dict:
    """Return a shallow copy of payload with formatted_plain and formatted_html added."""
    base = {k: v for k, v in payload.items() if k not in ("formatted_plain", "formatted_html")}
    plain = format_credit_application_plain(base, mask_sensitive=mask_sensitive)
    html_str = format_credit_application_html(base, mask_sensitive=mask_sensitive)
    return {**base, "formatted_plain": plain, "formatted_html": html_str}
