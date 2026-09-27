"""Who is in the dataset and how each vendor behaves (SPEC-02 §4).

Everything here is hand-written and fixed. Randomness (dates, amounts, invoice
counts) is applied later by `build.py`, so a vendor's behaviour never depends
on the seed.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from backend.app.domain.entities import Client, Firm
from backend.app.domain.enums import ExceptionType
from backend.app.domain.gstin import make_gstin

PERIODS = ("2026-01", "2026-02", "2026-03", "2026-04")
JAN, FEB, MAR, APR = PERIODS

HOME_STATE = "36"  # Telangana: the firm and all its clients

FIRM = Firm(firm_id="rao-associates", name="Rao & Associates")

CLIENTS = (
    Client(
        client_id="C01",
        name="Sri Balaji Textiles",
        gstin=make_gstin(HOME_STATE, "ABKFS4821M"),
        business_type="Textile trader, Begum Bazaar",
    ),
    Client(
        client_id="C02",
        name="Spice Route Restaurant",
        gstin=make_gstin(HOME_STATE, "AAQFS7730K"),
        business_type="Restaurant, Gachibowli",
    ),
    Client(
        client_id="C03",
        name="Vega Electronics Distributors",
        gstin=make_gstin(HOME_STATE, "AAHCV5516R"),
        business_type="Electronics distributor, Secunderabad",
    ),
)


class Treatment(StrEnum):
    """What happens to one invoice between the vendor's bill and the two files."""

    NORMAL = "NORMAL"
    FILED_LATE = "FILED_LATE"
    """Vendor files after the cut-off: appears in the next period's 2B."""
    NEVER_FILED = "NEVER_FILED"
    AMENDED_NEXT_MONTH = "AMENDED_NEXT_MONTH"
    """Filed against a wrong buyer GSTIN, amended in the next month's return."""
    ROUNDED_IN_2B = "ROUNDED_IN_2B"
    """The vendor's filed total differs from the bill by ₹2 to ₹9."""
    BOOKED_WRONG_TAX_HEAD = "BOOKED_WRONG_TAX_HEAD"
    """An inter-state bill booked as CGST + SGST."""
    ITC_BLOCKED = "ITC_BLOCKED"
    """In 2B with ITC not available (supplier registration cancelled)."""
    NOT_BOOKED = "NOT_BOOKED"
    """In 2B, but the client never gave the bill to the bookkeeper."""
    BOOKED_WRONG_GSTIN = "BOOKED_WRONG_GSTIN"
    """The bookkeeper mistyped one character of the supplier's GSTIN."""
    DISPUTED_AMOUNT = "DISPUTED_AMOUNT"
    """The vendor filed about 10% less than the bill: ambiguous on purpose."""


EXPECTED_EXCEPTION: dict[Treatment, ExceptionType | None] = {
    Treatment.NORMAL: None,
    Treatment.FILED_LATE: ExceptionType.MISSING_IN_2B,
    Treatment.NEVER_FILED: ExceptionType.MISSING_IN_2B,
    Treatment.AMENDED_NEXT_MONTH: ExceptionType.MISSING_IN_2B,
    Treatment.ROUNDED_IN_2B: ExceptionType.AMOUNT_MISMATCH,
    Treatment.BOOKED_WRONG_TAX_HEAD: ExceptionType.TAX_HEAD_MISMATCH,
    Treatment.ITC_BLOCKED: ExceptionType.ITC_INELIGIBLE,
    Treatment.NOT_BOOKED: ExceptionType.MISSING_IN_BOOKS,
    Treatment.BOOKED_WRONG_GSTIN: ExceptionType.GSTIN_MISMATCH,
    Treatment.DISPUTED_AMOUNT: ExceptionType.AMOUNT_MISMATCH,
}
"""The exception the matcher must raise, in the invoice's own period."""

Plan = Callable[[str, int], Treatment]
"""(period, index of the invoice within that client-month) → treatment."""


def always(treatment: Treatment) -> Plan:
    return lambda period, index: treatment


def in_periods(periods: set[str], treatment: Treatment, otherwise: Plan) -> Plan:
    return lambda period, index: treatment if period in periods else otherwise(period, index)


def first_invoice_in(periods: set[str], treatment: Treatment) -> Plan:
    """Only one invoice of the month is affected; the rest are normal."""
    return lambda period, index: treatment if period in periods and index == 0 else Treatment.NORMAL


@dataclass(frozen=True)
class NumberFormat:
    """How the vendor's invoice number is written in the client's books vs in 2B.

    Templates take `n` (the running number) and `fy` (e.g. "2025-26"). Both
    sides must normalize to the same key (SPEC-03 §4).
    """

    books: str
    twob: str

    @classmethod
    def same(cls, template: str) -> "NumberFormat":
        return cls(template, template)


@dataclass(frozen=True)
class Supplies:
    """A vendor supplying one client."""

    client_id: str
    periods: tuple[str, ...] = PERIODS
    invoices_per_month: tuple[int, int] = (3, 5)


@dataclass(frozen=True)
class VendorProfile:
    key: str
    name: str
    state: str
    pan: str
    hsn: str
    gst_rate: Decimal
    numbers: NumberFormat
    supplies: tuple[Supplies, ...]
    archetype: str = "RELIABLE"
    """Generator and eval only. Never part of the domain model (SPEC-01 D12)."""
    plan: Plan = field(default=always(Treatment.NORMAL), compare=False)
    cancelled_from: str | None = None

    @property
    def gstin(self) -> str:
        return make_gstin(self.state, self.pan)

    @property
    def client_ids(self) -> tuple[str, ...]:
        return tuple(supply.client_id for supply in self.supplies)


FIVE = Decimal("0.05")
EIGHTEEN = Decimal("0.18")
FEW = (1, 2)  # invoices per month for planted vendors: keeps exceptions near 15%

PLANTED_VENDORS = (
    VendorProfile(
        key="reddy_steels",
        name="Reddy Steels",
        state="36",
        pan="AABCR1234F",
        hsn="7326",
        gst_rate=EIGHTEEN,
        numbers=NumberFormat.same("RS/{fy}/{n:04d}"),
        supplies=(Supplies("C01", invoices_per_month=FEW),),
        archetype="LATE_FILER_THEN_DRIFT",
        plan=in_periods({JAN, FEB}, Treatment.FILED_LATE, always(Treatment.NEVER_FILED)),
    ),
    VendorProfile(
        key="bhavani_chemicals",
        name="Bhavani Chemicals",
        state="36",
        pan="AAFFB6621C",
        hsn="3402",
        gst_rate=EIGHTEEN,
        numbers=NumberFormat("BC-{n}", "BC/{n}"),
        supplies=(Supplies("C02", invoices_per_month=FEW),),
        archetype="LATE_FILER_CONSISTENT",
        plan=always(Treatment.FILED_LATE),
    ),
    VendorProfile(
        key="laxmi_packaging",
        name="Laxmi Packaging",
        state="36",
        pan="AAKFL3398P",
        hsn="4819",
        gst_rate=EIGHTEEN,
        numbers=NumberFormat("LP-{n}", "LP{n}"),
        supplies=(Supplies("C01", invoices_per_month=FEW), Supplies("C02", invoices_per_month=FEW)),
        archetype="ROUNDING",
        plan=always(Treatment.ROUNDED_IN_2B),
    ),
    VendorProfile(
        key="sai_electricals",
        name="Sai Electricals",
        state="36",
        pan="ABOFS2275E",
        hsn="8536",
        gst_rate=EIGHTEEN,
        numbers=NumberFormat("SE-{n}", "SE/{n}"),
        supplies=(Supplies("C03", invoices_per_month=FEW),),
        archetype="WRONG_BUYER_GSTIN",
        plan=in_periods({JAN, MAR}, Treatment.AMENDED_NEXT_MONTH, always(Treatment.NORMAL)),
    ),
    VendorProfile(
        key="mumbai_threads",
        name="Mumbai Threads",
        state="27",
        pan="AACCM8854T",
        hsn="5401",
        gst_rate=FIVE,
        numbers=NumberFormat("MT/{fy}/{n}", "MT/{fy}/{n}"),
        supplies=(Supplies("C01", invoices_per_month=FEW),),
        archetype="INTERSTATE_BOOKING_ERROR",
        plan=always(Treatment.BOOKED_WRONG_TAX_HEAD),
    ),
    VendorProfile(
        key="krishna_logistics",
        name="Krishna Logistics",
        state="36",
        pan="AAJFK4410L",
        hsn="9967",
        gst_rate=EIGHTEEN,
        numbers=NumberFormat("KL-{n}", "KL{n}"),
        supplies=(
            Supplies("C01", invoices_per_month=FEW),
            Supplies("C03", periods=(MAR, APR), invoices_per_month=FEW),
        ),
        archetype="NON_FILER_CROSS_CLIENT",
        plan=always(Treatment.NEVER_FILED),
    ),
    VendorProfile(
        key="om_sai_enterprises",
        name="Om Sai Enterprises",
        state="36",
        pan="AGEPO9163H",
        hsn="1509",
        gst_rate=FIVE,
        numbers=NumberFormat("OSE/{n}", "OSE/{n}"),
        supplies=(Supplies("C02", periods=(JAN, FEB, MAR), invoices_per_month=FEW),),
        archetype="CANCELLED",
        plan=in_periods({FEB, MAR}, Treatment.ITC_BLOCKED, always(Treatment.NORMAL)),
        cancelled_from=FEB,
    ),
    VendorProfile(
        key="ganesh_traders",
        name="Ganesh Traders",
        state="36",
        pan="ACDPG5507N",
        hsn="0904",
        gst_rate=FIVE,
        numbers=NumberFormat("INV/{n:04d}", "{n}"),
        supplies=(Supplies("C02", invoices_per_month=(2, 3)),),
        archetype="UNBOOKED",
        plan=first_invoice_in(set(PERIODS), Treatment.NOT_BOOKED),
    ),
    VendorProfile(
        key="venkateswara_components",
        name="Venkateswara Components",
        state="29",
        pan="AADCV7712B",
        hsn="8542",
        gst_rate=EIGHTEEN,
        numbers=NumberFormat.same("VC{fy}-{n}"),
        supplies=(Supplies("C03", invoices_per_month=FEW),),
        archetype="BOOKS_GSTIN_TYPO",
        plan=first_invoice_in({FEB, APR}, Treatment.BOOKED_WRONG_GSTIN),
    ),
    VendorProfile(
        key="deccan_power",
        name="Deccan Power Solutions",
        state="36",
        pan="AAECD3345Q",
        hsn="8504",
        gst_rate=EIGHTEEN,
        numbers=NumberFormat("DPS-{n}", "DPS/{fy}/{n}"),
        supplies=(Supplies("C03", invoices_per_month=FEW),),
        archetype="AMBIGUOUS",
        plan=first_invoice_in({APR}, Treatment.DISPUTED_AMOUNT),
    ),
)


def _reliable(
    key: str,
    name: str,
    state: str,
    pan: str,
    hsn: str,
    rate: Decimal,
    numbers: NumberFormat,
    *client_ids: str,
) -> VendorProfile:
    return VendorProfile(
        key=key,
        name=name,
        state=state,
        pan=pan,
        hsn=hsn,
        gst_rate=rate,
        numbers=numbers,
        supplies=tuple(Supplies(client_id) for client_id in client_ids),
    )


RELIABLE_VENDORS = (
    # Telangana
    _reliable("charminar_fabrics", "Charminar Fabrics", "36", "AAHFC1180D", "5208", FIVE,
              NumberFormat.same("CF/{fy}/{n:04d}"), "C01"),
    _reliable("golconda_silk", "Golconda Silk House", "36", "AAJFG2291A", "5007", FIVE,
              NumberFormat("GSH-{n}", "GSH{n}"), "C01"),
    _reliable("ameerpet_office", "Ameerpet Office Supplies", "36", "ABFPA6632K", "4820", EIGHTEEN,
              NumberFormat("AOS/{n:05d}", "AOS/{n}"), "C01", "C02", "C03"),
    _reliable("kukatpally_kitchen", "Kukatpally Kitchen Equipment", "36", "AAKCK4471G", "7323",
              EIGHTEEN, NumberFormat.same("KKE/{fy}/{n}"), "C02"),
    _reliable("nampally_spices", "Nampally Spices & Dry Fruits", "36", "AMTPN3318J", "0908", FIVE,
              NumberFormat("INV/{n:04d}", "{n}"), "C02"),
    _reliable("banjara_dairy", "Banjara Hills Dairy", "36", "AAIFB8804R", "0405", FIVE,
              NumberFormat("BHD-{n}", "BHD/{n}"), "C02"),
    _reliable("begumpet_gas", "Begumpet Gas Agency", "36", "AAGFB5529M", "2711", EIGHTEEN,
              NumberFormat.same("BGA{n:05d}"), "C02"),
    _reliable("madhapur_hardware", "Madhapur IT Hardware", "36", "AAMCM1906S", "8471", EIGHTEEN,
              NumberFormat("MIH-{n}", "MIH{n}"), "C03"),
    # Maharashtra
    _reliable("bhiwandi_weaving", "Bhiwandi Weaving Mills", "27", "AABCB7043E", "5407", FIVE,
              NumberFormat.same("BWM/{fy}/{n}"), "C01"),
    _reliable("nashik_agro", "Nashik Agro Foods", "27", "AAFCN2268P", "2001", FIVE,
              NumberFormat("NAF-{n}", "NAF/{n}"), "C02"),
    _reliable("pune_cables", "Pune Cables", "27", "AAECP9915H", "8544", EIGHTEEN,
              NumberFormat.same("PC/{fy}/{n:04d}"), "C03"),
    # Karnataka
    _reliable("peenya_tools", "Peenya Precision Tools", "29", "AAHCP4436L", "8207", EIGHTEEN,
              NumberFormat("PPT-{n}", "PPT{n}"), "C03"),
    _reliable("mysore_silk", "Mysore Silk Emporium", "29", "AAJFM6652C", "5007", FIVE,
              NumberFormat.same("MSE/{n}"), "C01"),
    # Tamil Nadu
    _reliable("tiruppur_knits", "Tiruppur Knit Garments", "33", "AADFT3375B", "6109", FIVE,
              NumberFormat("TKG-{n}", "TKG/{n}"), "C01"),
    _reliable("chennai_seafood", "Chennai Seafood Traders", "33", "AAGFC8127Q", "0306", FIVE,
              NumberFormat.same("CST/{fy}/{n}"), "C02"),
    _reliable("coimbatore_motors", "Coimbatore Motor Works", "33", "AACCC5580F", "8501", EIGHTEEN,
              NumberFormat("CMW-{n}", "CMW{n}"), "C03"),
)  # fmt: skip

VENDORS = PLANTED_VENDORS + RELIABLE_VENDORS
