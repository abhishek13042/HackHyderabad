"""Tax head rule (SPEC-01 §4): same state → CGST+SGST, different state → IGST."""

from decimal import Decimal

from backend.app.domain.enums import TaxHead


class TaxHeadError(ValueError):
    """Raised when an invoice's tax amounts don't follow a single tax head."""


def expected_tax_head(supplier_state: str, place_of_supply: str) -> TaxHead:
    return TaxHead.INTRA if supplier_state == place_of_supply else TaxHead.INTER


def charged_tax_head(cgst: Decimal, sgst: Decimal, igst: Decimal) -> TaxHead | None:
    """The tax head an invoice was actually booked or filed under.

    Returns None for a zero-tax invoice, which has no head.
    """
    has_intra = cgst != 0 or sgst != 0
    has_inter = igst != 0
    if has_intra and has_inter:
        raise TaxHeadError(f"both CGST/SGST and IGST charged: {cgst=}, {sgst=}, {igst=}")
    if has_intra:
        if cgst != sgst:
            raise TaxHeadError(f"CGST and SGST must be equal: {cgst=}, {sgst=}")
        return TaxHead.INTRA
    if has_inter:
        return TaxHead.INTER
    return None
