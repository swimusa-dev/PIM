"""Normalization applied to every ingest and import (IMP-10, IMP-11, DM-01 F7).

- Placeholder tokens become null. "Not applicable" stays an explicit answer where the attribute allows it.
- Identifiers get a normalized form (uppercase, separators stripped) so every alias of a product resolves the same way.
- ERP raw option values are mapped to clean option codes; unmapped or test-looking values become ERP defects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DEFAULT_PLACEHOLDERS: dict[str, bool] = {
    "-": False,
    "--": False,
    "undefined": False,
    "no desc": False,
    "tbd": False,
    "place holder": False,
    "placeholder": False,
    "null": False,
    "none": False,
    "n/a": True,
    "na": True,
    "not applicable": True,
    "not required": True,
}

_QUOTES_AND_SPACE = re.compile(r"""^[\s"'“”‘’`]+$""")
_STRIP_QUOTES = re.compile(r"""^[\s"'“”‘’`]+|[\s"'“”‘’`]+$""")
_IDENT_STRIP = re.compile(r"[^A-Z0-9]")
_OPTION_STRIP = re.compile(r"[^A-Z0-9 ]")
_MULTI_SPACE = re.compile(r"\s+")
_DATE_LIKE = re.compile(r"^\d{1,2}[./-]\d{1,2}([./-]\d{2,4})?$")
_TEST_WORDS = re.compile(r"^(TEST|ABC|XXX|DUMMY|SAMPLE|TBD)\w*$", re.IGNORECASE)


@dataclass
class NormalizeResult:
    value: str | None
    not_applicable: bool = False
    was_placeholder: bool = False


class Normalizer:
    """Holds the configured placeholder list (seeded from placeholders.yml, editable by admins)."""

    def __init__(self, placeholders: dict[str, bool] | None = None) -> None:
        self.placeholders = {k.strip().lower(): v for k, v in (placeholders or DEFAULT_PLACEHOLDERS).items()}

    def normalize_text(
        self, raw: object, *, allows_not_applicable: bool = False, not_required_means_na: bool = False
    ) -> NormalizeResult:
        if raw is None:
            return NormalizeResult(None)
        s = str(raw)
        if _QUOTES_AND_SPACE.match(s) or s.strip() == "":
            return NormalizeResult(None, was_placeholder=s.strip() != "" or len(s) > 0)
        cleaned = _STRIP_QUOTES.sub("", s).strip()
        if cleaned == "":
            return NormalizeResult(None, was_placeholder=True)
        key = cleaned.lower()
        if key in self.placeholders:
            means_na = self.placeholders[key]
            if key == "not required":
                means_na = not_required_means_na
            if means_na and allows_not_applicable:
                return NormalizeResult(None, not_applicable=True, was_placeholder=True)
            return NormalizeResult(None, was_placeholder=True)
        return NormalizeResult(cleaned)


def normalize_identifier(value: object) -> str:
    """`200809-FVP`, `200809FVP`, ` 200809 fvp ` -> `200809FVP` (DM-01, F7)."""
    if value is None:
        return ""
    return _IDENT_STRIP.sub("", str(value).upper())


def normalize_raw_option(value: object) -> str:
    """Key used to look up value mappings: upper, punctuation removed, spaces collapsed (IMP-11, F6)."""
    if value is None:
        return ""
    s = _OPTION_STRIP.sub(" ", str(value).upper())
    return _MULTI_SPACE.sub(" ", s).strip()


def looks_like_test_value(value: str) -> str | None:
    """Returns a defect reason when the value looks like test data (IMP-11): `ABC`, `TESTMAT1`, `10.30`."""
    v = value.strip()
    if not v:
        return None
    if _DATE_LIKE.match(v):
        return "date_in_text"
    if _TEST_WORDS.match(v):
        return "test_value"
    return None


@dataclass
class MappingOutcome:
    option_code: str | None
    defect_reason: str | None = None
    raw: str = ""
    extra: dict = field(default_factory=dict)


def map_raw_to_option(raw: str, mappings: dict[str, str | None], valid_codes: set[str]) -> MappingOutcome:
    """Map an ERP raw value to an option code using remembered mappings (IMP-03/IMP-11).

    `mappings` is keyed by normalized raw value. A direct hit on an option code or label (normalized) also counts.
    """
    key = normalize_raw_option(raw)
    if key in mappings:
        code = mappings[key]
        return MappingOutcome(code, None if code else "unmapped", raw)
    test = looks_like_test_value(raw)
    if test:
        return MappingOutcome(None, test, raw)
    lowered = key.lower().replace(" ", "_")
    if lowered in valid_codes:
        return MappingOutcome(lowered, None, raw)
    return MappingOutcome(None, "unmapped", raw)
