"""AC-01-4: the safety invariants INV-1 and INV-2."""

import pytest

from backend.app.domain.enums import Action, ExceptionType
from backend.app.domain.policy import ALLOWED_ACTIONS, can_auto_resolve, is_action_allowed


def test_every_exception_type_has_rules() -> None:
    assert set(ALLOWED_ACTIONS) == set(ExceptionType)


@pytest.mark.parametrize("exception_type", list(ExceptionType))
def test_escalate_is_always_possible(exception_type: ExceptionType) -> None:
    assert is_action_allowed(exception_type, Action.ESCALATE)


@pytest.mark.parametrize(
    "exception_type", [ExceptionType.MISSING_IN_2B, ExceptionType.ITC_INELIGIBLE]
)
def test_inv1_never_accept_credit_that_is_not_in_2b(exception_type: ExceptionType) -> None:
    assert not is_action_allowed(exception_type, Action.ACCEPT)
    assert not can_auto_resolve(exception_type, Action.ACCEPT)


@pytest.mark.parametrize("exception_type", list(ExceptionType))
@pytest.mark.parametrize("action", list(Action))
def test_inv2_only_accept_or_defer_can_be_automatic(
    exception_type: ExceptionType, action: Action
) -> None:
    if can_auto_resolve(exception_type, action):
        assert action in {Action.ACCEPT, Action.DEFER}
        assert is_action_allowed(exception_type, action)


def test_rules_are_read_only() -> None:
    with pytest.raises(TypeError):
        ALLOWED_ACTIONS[ExceptionType.MISSING_IN_2B] = frozenset({Action.ACCEPT})  # type: ignore[index]
