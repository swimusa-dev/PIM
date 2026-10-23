"""IMP-10, IMP-11, DM-01 (F2, F6, F7)."""

from pim.normalization import (
    Normalizer,
    looks_like_test_value,
    map_raw_to_option,
    normalize_identifier,
    normalize_raw_option,
)


def test_imp10_placeholders_become_null():
    n = Normalizer()
    for raw in ["-", "--", "Undefined", "NO DESC", "   ", 'place holder"', "TBD", '"', "“”"]:
        r = n.normalize_text(raw)
        assert r.value is None, raw
        assert r.was_placeholder, raw


def test_imp10_not_applicable_is_explicit_only_when_allowed():
    n = Normalizer()
    assert n.normalize_text("N/A", allows_not_applicable=True).not_applicable is True
    assert n.normalize_text("N/A", allows_not_applicable=False).not_applicable is False
    assert n.normalize_text("N/A", allows_not_applicable=False).value is None
    # NOT REQUIRED maps to Not applicable only where the admin says so per attribute
    assert n.normalize_text("NOT REQUIRED", allows_not_applicable=True).not_applicable is False
    assert n.normalize_text("NOT REQUIRED", allows_not_applicable=True, not_required_means_na=True).not_applicable is True


def test_imp10_real_values_survive_with_stray_quotes_stripped():
    n = Normalizer()
    assert n.normalize_text(' Hand Wash Cold" ').value == "Hand Wash Cold"
    assert n.normalize_text("0").value == "0"


def test_dm01_identifier_aliases_normalize_to_one_key():
    assert normalize_identifier("200809-FVP") == normalize_identifier("200809FVP") == normalize_identifier(" 200809 fvp ")
    assert normalize_identifier("LONG LINE BRALETTE:XL:FSTVL PINK") == "LONGLINEBRALETTEXLFSTVLPINK"


def test_imp11_option_mapping_and_defects():
    mappings = {normalize_raw_option(k): v for k, v in {"ADJUSTABLE": "adjustable", "Adjustable": "adjustable",
                                                          "Recycled Claim Standard (RCS)": "rcs"}.items()}
    assert map_raw_to_option("adjustable ", mappings, {"adjustable"}).option_code == "adjustable"
    assert map_raw_to_option("RECYCLED CLAIM STANDARD RCS", mappings, {"rcs"}).option_code == "rcs"
    assert map_raw_to_option("ABC", {}, {"rcs"}).defect_reason == "test_value"
    assert map_raw_to_option("TESTMAT1", {}, {"rcs"}).defect_reason == "test_value"
    assert map_raw_to_option("10.30", {}, {"rcs"}).defect_reason == "date_in_text"
    assert map_raw_to_option("Something Else", {}, {"rcs"}).defect_reason == "unmapped"
    assert looks_like_test_value("Hook and eye") is None
