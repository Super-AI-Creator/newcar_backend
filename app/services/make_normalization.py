from __future__ import annotations

import re
from typing import Iterable, Optional

_CANONICAL_MAKE_ORDER = [
    "Acura",
    "Alfa Romeo",
    "Audi",
    "BMW",
    "Buick",
    "Cadillac",
    "Chevrolet",
    "Chrysler",
    "Dodge",
    "FIAT",
    "Ford",
    "Genesis",
    "GMC",
    "Honda",
    "Hyundai",
    "INEOS",
    "INFINITI",
    "Jaguar",
    "Jeep",
    "Kia",
    "Land Rover",
    "Lexus",
    "Lincoln",
    "Maserati",
    "Mazda",
    "Mercedes-Benz",
    "MINI",
    "Mitsubishi",
    "Nissan",
    "Porsche",
    "Ram",
    "Subaru",
    "Toyota",
    "VinFast",
    "Volkswagen",
    "Volvo",
]

_CANONICAL_INDEX = {name: idx for idx, name in enumerate(_CANONICAL_MAKE_ORDER)}

_ALIASES_BY_CANONICAL = {
    "Genesis": {"genesvs", "genesis"},
    "INFINITI": {"infiniti"},
    "Kia": {"kia"},
    "Land Rover": {"landrover", "land rover", "land\u2022rover", "landver"},
    "Lexus": {"lexus"},
    "Mercedes-Benz": {"mercedesbenz", "mercedes benz", "mercedes-benz"},
    "VinFast": {"vinfast", "vin fast"},
    "FIAT": {"fiat"},
    "GMC": {"gmc"},
    "INEOS": {"ineos"},
    "MINI": {"mini"},
}


def normalize_text_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").strip().lower())


def _build_alias_to_canonical() -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for canonical in _CANONICAL_MAKE_ORDER:
        alias_map[normalize_text_token(canonical)] = canonical
    for canonical, aliases in _ALIASES_BY_CANONICAL.items():
        for alias in aliases:
            alias_map[normalize_text_token(alias)] = canonical
    return alias_map


_ALIAS_TO_CANONICAL = _build_alias_to_canonical()


def canonicalize_make(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    key = normalize_text_token(raw)
    if not key:
        return None
    return _ALIAS_TO_CANONICAL.get(key, raw)


def canonical_make_filter_tokens(value: Optional[str]) -> set[str]:
    canonical = canonicalize_make(value)
    if not canonical:
        return set()
    tokens = {normalize_text_token(canonical)}
    for alias in _ALIASES_BY_CANONICAL.get(canonical, set()):
        normalized = normalize_text_token(alias)
        if normalized:
            tokens.add(normalized)
    return tokens


def canonical_make_sort_key(value: str):
    idx = _CANONICAL_INDEX.get(value)
    if idx is not None:
        return (0, idx, value.lower())
    return (1, 10_000, value.lower())


def canonicalize_make_values(values: Iterable[object]) -> list[str]:
    out: set[str] = set()
    for value in values:
        canonical = canonicalize_make(str(value) if value is not None else None)
        if canonical:
            out.add(canonical)
    return sorted(out, key=canonical_make_sort_key)
