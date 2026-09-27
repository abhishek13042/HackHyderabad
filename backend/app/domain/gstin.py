"""GSTIN format and check character (SPEC-01 §3).

Layout: SS PPPPPPPPPP E Z C
  SS  state code        PPPPPPPPPP  PAN (5 letters, 4 digits, 1 letter)
  E   entity number     Z           literal 'Z'       C  check character
"""

import re
from typing import Annotated

from pydantic import AfterValidator

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_LENGTH = 15

_FORMAT = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_PAN_FORMAT = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")


class GstinError(ValueError):
    """Raised for a malformed GSTIN or one with a wrong check character."""


def check_character(first_14: str) -> str:
    """Compute the check character for the first 14 characters of a GSTIN."""
    if len(first_14) != GSTIN_LENGTH - 1:
        raise GstinError(f"expected 14 characters, got {len(first_14)}: {first_14!r}")
    total = 0
    for position, char in enumerate(first_14):
        if char not in ALPHABET:
            raise GstinError(f"invalid character {char!r} in {first_14!r}")
        factor = 1 if position % 2 == 0 else 2
        product = ALPHABET.index(char) * factor
        total += product // len(ALPHABET) + product % len(ALPHABET)
    return ALPHABET[(len(ALPHABET) - total % len(ALPHABET)) % len(ALPHABET)]


def validate_gstin(value: str) -> str:
    """Return the GSTIN normalized to upper case, or raise `GstinError`."""
    gstin = value.strip().upper()
    if not _FORMAT.fullmatch(gstin):
        raise GstinError(f"not a GSTIN (wrong format): {value!r}")
    if gstin[-1] != check_character(gstin[:-1]):
        raise GstinError(f"not a GSTIN (wrong check character): {value!r}")
    return gstin


def is_valid_gstin(value: str) -> bool:
    try:
        validate_gstin(value)
    except GstinError:
        return False
    return True


def make_gstin(state_code: str, pan: str, entity: str = "1") -> str:
    """Build a valid GSTIN from its parts (used by the synthetic data generator)."""
    if not (len(state_code) == 2 and state_code.isdigit()):
        raise GstinError(f"state code must be two digits: {state_code!r}")
    if not _PAN_FORMAT.fullmatch(pan):
        raise GstinError(f"not a PAN: {pan!r}")
    first_14 = f"{state_code}{pan}{entity}Z"
    return validate_gstin(first_14 + check_character(first_14))


def state_code(gstin: str) -> str:
    """The two-digit state code a GSTIN is registered in."""
    return validate_gstin(gstin)[:2]


Gstin = Annotated[str, AfterValidator(validate_gstin)]
"""Pydantic field type for a validated GSTIN."""
