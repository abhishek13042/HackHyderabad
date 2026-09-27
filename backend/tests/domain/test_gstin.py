import pytest

from backend.app.domain.gstin import (
    ALPHABET,
    GstinError,
    check_character,
    is_valid_gstin,
    make_gstin,
    state_code,
    validate_gstin,
)

# Publicly listed GSTINs, used as fixed points for the check-character algorithm.
REAL_GSTINS = ["27AAPFU0939F1ZV", "29AAGCB7383J1Z4"]


@pytest.mark.parametrize("gstin", REAL_GSTINS)
def test_accepts_real_gstins(gstin: str) -> None:
    assert validate_gstin(gstin) == gstin


def test_normalizes_case_and_whitespace() -> None:
    assert validate_gstin("  27aapfu0939f1zv ") == "27AAPFU0939F1ZV"


def test_make_gstin_builds_a_valid_gstin() -> None:
    gstin = make_gstin("36", "AABCR1234F")
    assert gstin.startswith("36AABCR1234F1Z")
    assert is_valid_gstin(gstin)
    assert state_code(gstin) == "36"


@pytest.mark.parametrize("gstin", [*REAL_GSTINS, make_gstin("36", "AABCR1234F", entity="2")])
def test_rejects_every_single_character_change(gstin: str) -> None:
    """AC-01-1: any one changed character is caught (format or check character)."""
    for position, original in enumerate(gstin):
        for replacement in ALPHABET:
            if replacement == original:
                continue
            changed = gstin[:position] + replacement + gstin[position + 1 :]
            assert not is_valid_gstin(changed), changed


@pytest.mark.parametrize(
    "value",
    [
        "",
        "27AAPFU0939F1Z",
        "27AAPFU0939F1ZVX",
        "27AAPFU0939F0ZV",
        "27AAPFU0939F1YV",
        "2?AAPFU0939F1ZV",
    ],
)
def test_rejects_malformed(value: str) -> None:
    with pytest.raises(GstinError):
        validate_gstin(value)


def test_check_character_requires_14_characters() -> None:
    with pytest.raises(GstinError):
        check_character("27AAPFU0939F1")


@pytest.mark.parametrize(
    ("state", "pan"), [("3", "AABCR1234F"), ("36", "AABCR1234"), ("36", "1ABCR1234F")]
)
def test_make_gstin_rejects_bad_parts(state: str, pan: str) -> None:
    with pytest.raises(GstinError):
        make_gstin(state, pan)
