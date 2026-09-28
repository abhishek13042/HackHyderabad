"""Safety rules (SPEC-01 §7, SPEC-05 §4). Code enforces these; the LLM cannot bypass them.

INV-1: ACCEPT is never valid for MISSING_IN_2B or ITC_INELIGIBLE
       (it would mean claiming credit that isn't in GSTR-2B).
INV-2: only ACCEPT and DEFER may ever be resolved automatically.
"""

from decimal import Decimal
from types import MappingProxyType

from backend.app.domain.enums import Action, ExceptionType, TrustLevel

ALLOWED_ACTIONS: MappingProxyType[ExceptionType, frozenset[Action]] = MappingProxyType(
    {
        ExceptionType.MISSING_IN_2B: frozenset(
            {Action.DEFER, Action.CHASE_VENDOR, Action.HOLD_PAYMENT, Action.ESCALATE}
        ),
        ExceptionType.MISSING_IN_BOOKS: frozenset({Action.BOOK_INVOICE, Action.ESCALATE}),
        ExceptionType.AMOUNT_MISMATCH: frozenset(
            {Action.ACCEPT, Action.CHASE_VENDOR, Action.CORRECT_BOOKS, Action.ESCALATE}
        ),
        ExceptionType.TAX_HEAD_MISMATCH: frozenset(
            {Action.CORRECT_BOOKS, Action.CHASE_VENDOR, Action.ESCALATE}
        ),
        ExceptionType.GSTIN_MISMATCH: frozenset(
            {Action.CORRECT_BOOKS, Action.CHASE_VENDOR, Action.ESCALATE}
        ),
        ExceptionType.ITC_INELIGIBLE: frozenset(
            {Action.BLOCK_ITC, Action.CHASE_VENDOR, Action.ESCALATE}
        ),
    }
)
"""Actions an accountant or the agent may take for each exception type."""

AUTO_RESOLVABLE_ACTIONS: frozenset[Action] = frozenset({Action.ACCEPT, Action.DEFER})
"""INV-2: the only actions that may be taken without a human."""


def is_action_allowed(exception_type: ExceptionType, action: Action) -> bool:
    return action in ALLOWED_ACTIONS[exception_type]


def can_auto_resolve(exception_type: ExceptionType, action: Action) -> bool:
    return action in AUTO_RESOLVABLE_ACTIONS and is_action_allowed(exception_type, action)


CONFIDENCE_CAPS: MappingProxyType[TrustLevel, float] = MappingProxyType(
    {TrustLevel.OBSERVE: 0.6, TrustLevel.SUGGEST: 0.85, TrustLevel.AUTO: 1.0}
)
"""SPEC-06: the most confidence a suggestion may show at each trust level."""

MAX_ACCEPTABLE_DIFF = Decimal("500.00")
"""SPEC-05 G4: above this, an amount difference is never simply accepted."""
