"""Domain entities (SPEC-01 §5).

Immutable Pydantic models. Money is `Decimal` (see `money.py`); ids are None
until a row is persisted. Invariants that belong to the data itself are checked
here, so an invalid entity can't be constructed anywhere in the system.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    computed_field,
    model_serializer,
    model_validator,
)

from backend.app.domain.enums import (
    Action,
    DecidedBy,
    ExceptionType,
    OutcomeStatus,
    RegistrationStatus,
    TaxHead,
)
from backend.app.domain.gstin import Gstin
from backend.app.domain.money import Money
from backend.app.domain.periods import Period
from backend.app.domain.policy import can_auto_resolve, is_action_allowed
from backend.app.domain.tax import charged_tax_head

StateCode = Annotated[str, StringConstraints(pattern=r"^\d{2}$")]
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ClientId = Annotated[str, StringConstraints(pattern=r"^C\d{2}$")]
NonNegativeMoney = Annotated[Money, Field(ge=0)]

GROUP_KEY_SEPARATOR = ":"


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Firm, clients, vendors --------------------------------------------------


class Firm(DomainModel):
    firm_id: NonEmptyStr
    name: NonEmptyStr


class Client(DomainModel):
    client_id: ClientId
    name: NonEmptyStr
    gstin: Gstin
    business_type: NonEmptyStr

    @property
    def state_code(self) -> str:
        return self.gstin[:2]


class Vendor(DomainModel):
    """A supplier, keyed by GSTIN.

    Deliberately has no `archetype`: the planted behaviour label exists only in
    the data generator and ground truth, so it can never leak to the agent.
    """

    gstin: Gstin
    name: NonEmptyStr
    registration_status: RegistrationStatus = RegistrationStatus.ACTIVE

    @property
    def state_code(self) -> str:
        return self.gstin[:2]


# --- Invoices ----------------------------------------------------------------


class _TaxAmounts(DomainModel):
    taxable_value: NonNegativeMoney
    cgst: NonNegativeMoney
    sgst: NonNegativeMoney
    igst: NonNegativeMoney
    cess: NonNegativeMoney
    total: NonNegativeMoney

    @property
    def tax_total(self) -> Decimal:
        return self.cgst + self.sgst + self.igst + self.cess

    @property
    def tax_head(self) -> TaxHead | None:
        return charged_tax_head(self.cgst, self.sgst, self.igst)


class BookInvoice(_TaxAmounts):
    """One row of a client's purchase register (Tally export)."""

    id: int | None = None
    client_id: ClientId
    period: Period
    voucher_date: date
    voucher_no: NonEmptyStr
    supplier_invoice_no: NonEmptyStr
    supplier_invoice_date: date
    supplier_name: NonEmptyStr
    supplier_gstin: Gstin
    place_of_supply: StateCode
    hsn: NonEmptyStr


class TwoBEntry(_TaxAmounts):
    """One invoice as reported by the supplier and shown in the client's GSTR-2B."""

    id: int | None = None
    client_id: ClientId
    period: Period
    supplier_gstin: Gstin
    supplier_name: NonEmptyStr
    supplier_period: Period
    supplier_filing_date: date | None
    invoice_no: NonEmptyStr
    invoice_date: date
    place_of_supply: StateCode
    itc_available: bool
    itc_unavailable_reason: str | None = None

    @model_validator(mode="after")
    def _reason_only_when_unavailable(self) -> Self:
        if self.itc_available and self.itc_unavailable_reason:
            raise ValueError("itc_unavailable_reason is only valid when ITC is unavailable")
        return self


# --- Exceptions --------------------------------------------------------------


class GroupKey(DomainModel):
    """Identifies an exception group: `client:period:vendor_gstin:type` (SPEC-03 §7).

    The agent and the accountant decide per group, never per invoice.
    """

    client_id: ClientId
    period: Period
    vendor_gstin: Gstin
    exception_type: ExceptionType

    @model_validator(mode="before")
    @classmethod
    def _parse_string(cls, data: Any) -> Any:
        if isinstance(data, str):
            parts = data.split(GROUP_KEY_SEPARATOR)
            if len(parts) != 4:
                raise ValueError(f"group key must have 4 parts: {data!r}")
            return dict(zip(cls.model_fields, parts, strict=True))
        return data

    @model_serializer
    def _as_string(self) -> str:
        return str(self)

    def __str__(self) -> str:
        return GROUP_KEY_SEPARATOR.join(
            (self.client_id, self.period, self.vendor_gstin, self.exception_type.value)
        )


class ReconException(DomainModel):
    """One invoice-level problem found by the matcher."""

    id: int | None = None
    client_id: ClientId
    period: Period
    type: ExceptionType
    vendor_gstin: Gstin
    book_invoice_id: int | None = None
    twob_entry_id: int | None = None
    itc_at_risk: NonNegativeMoney
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @property
    def group_key(self) -> GroupKey:
        return GroupKey(
            client_id=self.client_id,
            period=self.period,
            vendor_gstin=self.vendor_gstin,
            exception_type=self.type,
        )


# --- Decisions and outcomes --------------------------------------------------


class Decision(DomainModel):
    """How a group was resolved — by the accountant or automatically."""

    id: int | None = None
    group_key: GroupKey
    suggested_action: Action | None
    final_action: Action
    decided_by: DecidedBy
    note: str | None = None
    decided_at: AwareDatetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def accepted_suggestion(self) -> bool:
        return self.suggested_action is not None and self.suggested_action == self.final_action

    @model_validator(mode="after")
    def _enforce_safety(self) -> Self:
        exception_type = self.group_key.exception_type
        if not is_action_allowed(exception_type, self.final_action):
            # INV-1 lives in the allowed-actions table.
            raise ValueError(f"{self.final_action} is not allowed for {exception_type}")
        if self.decided_by is DecidedBy.AUTO:
            if not can_auto_resolve(exception_type, self.final_action):
                raise ValueError(f"{self.final_action} may not be auto-resolved (INV-2)")
            if not self.accepted_suggestion:
                raise ValueError("an automatic decision must apply the suggested action")
        return self


class Outcome(DomainModel):
    """The self-check verdict on a past decision (SPEC-06 §4)."""

    decision_id: int
    status: OutcomeStatus
    checked_in_period: Period
    evidence: dict[str, JsonValue] = Field(default_factory=dict)
