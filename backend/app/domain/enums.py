"""Every shared enum (SPEC-01 §6). The single place where these values are declared.

Other modules import from here; they never re-declare values (AC-01-2).
Enum values are the exact strings stored in SQLite, sent over the API and
returned by the LLM, so renaming a value is a breaking change.
"""

from enum import IntEnum, StrEnum


class ExceptionType(StrEnum):
    MISSING_IN_2B = "MISSING_IN_2B"
    """In the purchase register, not in GSTR-2B."""
    MISSING_IN_BOOKS = "MISSING_IN_BOOKS"
    """In GSTR-2B, not in the purchase register (unclaimed credit)."""
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    """Matched, but totals differ by more than the matcher tolerance."""
    TAX_HEAD_MISMATCH = "TAX_HEAD_MISMATCH"
    """Matched, but one side is IGST and the other CGST+SGST."""
    GSTIN_MISMATCH = "GSTIN_MISMATCH"
    """Same invoice found under a different supplier GSTIN."""
    ITC_INELIGIBLE = "ITC_INELIGIBLE"
    """In GSTR-2B with itcavl = N (e.g. supplier registration cancelled)."""


class Action(StrEnum):
    ACCEPT = "ACCEPT"
    """Accept the 2B figures; the difference is immaterial."""
    DEFER = "DEFER"
    """Don't claim this month; re-check next month's 2B."""
    CHASE_VENDOR = "CHASE_VENDOR"
    """Contact the vendor to file or amend GSTR-1."""
    HOLD_PAYMENT = "HOLD_PAYMENT"
    """Withhold the GST portion of the vendor's payment until it appears in 2B."""
    CORRECT_BOOKS = "CORRECT_BOOKS"
    """The client's entry is wrong; fix the purchase register."""
    BLOCK_ITC = "BLOCK_ITC"
    """Don't claim (or reverse) this credit."""
    BOOK_INVOICE = "BOOK_INVOICE"
    """Invoice missing from the books; verify with the client and book it."""
    ESCALATE = "ESCALATE"
    """The agent can't decide safely; a human must review."""


class RootCause(StrEnum):
    LATE_FILING = "LATE_FILING"
    NOT_FILED = "NOT_FILED"
    WRONG_BUYER_GSTIN = "WRONG_BUYER_GSTIN"
    ROUNDING = "ROUNDING"
    BOOKING_ERROR = "BOOKING_ERROR"
    SUPPLIER_CANCELLED = "SUPPLIER_CANCELLED"
    NOT_BOOKED = "NOT_BOOKED"
    UNKNOWN = "UNKNOWN"


class Flag(StrEnum):
    CROSS_CLIENT_RISK = "CROSS_CLIENT_RISK"
    """The vendor caused problems for another client of the firm."""
    PATTERN_DRIFT = "PATTERN_DRIFT"
    """The vendor broke its established pattern."""
    RECURRING_ISSUE = "RECURRING_ISSUE"
    """Same vendor, same exception type, in two or more prior periods."""
    VENDOR_RISK = "VENDOR_RISK"
    """The vendor is cancelled or high-risk; consider stopping purchases."""


class TrustLevel(IntEnum):
    OBSERVE = 0
    """The human decides; the suggestion is shown as low-confidence."""
    SUGGEST = 1
    """Confident suggestion; the human confirms."""
    AUTO = 2
    """Resolved automatically; the human can review and undo."""


class OutcomeStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED_CORRECT = "VERIFIED_CORRECT"
    VERIFIED_WRONG = "VERIFIED_WRONG"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DecidedBy(StrEnum):
    ACCOUNTANT = "ACCOUNTANT"
    AUTO = "AUTO"


class RegistrationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class TaxHead(StrEnum):
    INTRA = "INTRA"
    """Intra-state supply: CGST + SGST."""
    INTER = "INTER"
    """Inter-state supply: IGST."""
