"""Parsers for the two input files (SPEC-02 §5, §6): purchase register CSV and GSTR-2B JSON.

This module owns the file formats. The data generator writes files using the
constants defined here, so the writer and the reader can't drift apart.
"""

import csv
import io
import json
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from backend.app.domain.entities import BookInvoice, Client, TwoBEntry
from backend.app.domain.gstin import Gstin
from backend.app.domain.money import Money
from backend.app.domain.periods import from_return_period, to_return_period

DATE_FORMAT = "%d-%m-%Y"
"""Both files write dates as DD-MM-YYYY, as Tally and the GST portal do."""

PURCHASE_REGISTER_COLUMNS = (
    "voucher_date",
    "voucher_no",
    "supplier_invoice_no",
    "supplier_invoice_date",
    "supplier_name",
    "supplier_gstin",
    "place_of_supply",
    "hsn",
    "taxable_value",
    "cgst",
    "sgst",
    "igst",
    "cess",
    "total",
)

_PLAIN_REGISTER_COLUMNS = tuple(
    column for column in PURCHASE_REGISTER_COLUMNS if not column.endswith("_date")
)

ITC_AVAILABLE = "Y"
ITC_UNAVAILABLE = "N"


class IngestError(ValueError):
    """An input file doesn't follow the expected format. The message says where."""


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def parse_date(value: Any) -> Any:
    if isinstance(value, str):
        return datetime.strptime(value.strip(), DATE_FORMAT).date()  # noqa: DTZ007 (a date)
    return value


DmyDate = Annotated[date, BeforeValidator(parse_date)]


# --- Purchase register -------------------------------------------------------


def read_purchase_register(text: str, client: Client, period: str) -> list[BookInvoice]:
    """Parse a purchase register export for one client and period."""
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != PURCHASE_REGISTER_COLUMNS:
        raise IngestError(
            f"purchase register columns must be {', '.join(PURCHASE_REGISTER_COLUMNS)}; "
            f"got {', '.join(reader.fieldnames or ())}"
        )
    invoices = []
    for line_no, row in enumerate(reader, start=2):  # line 1 is the header
        try:
            invoices.append(
                BookInvoice(
                    client_id=client.client_id,
                    period=period,
                    voucher_date=parse_date(row["voucher_date"]),
                    supplier_invoice_date=parse_date(row["supplier_invoice_date"]),
                    **{key: row[key] for key in _PLAIN_REGISTER_COLUMNS},
                )
            )
        except (ValidationError, ValueError) as exc:
            raise IngestError(f"purchase register line {line_no}: {exc}") from exc
    return invoices


# --- GSTR-2B -----------------------------------------------------------------


class _Raw(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _RawInvoice(_Raw):
    inum: str
    dt: DmyDate
    val: Money
    pos: str
    rev: Literal["N"]  # reverse charge is out of scope (SPEC-02 §2)
    itcavl: Literal["Y", "N"]
    rsn: str = ""
    txval: Money
    igst: Money
    cgst: Money
    sgst: Money
    cess: Money


class _RawSupplier(_Raw):
    ctin: Gstin
    trdnm: str
    supprd: str
    supfildt: DmyDate | None = None
    inv: list[_RawInvoice]


class _RawDocData(_Raw):
    b2b: list[_RawSupplier] = Field(default_factory=list)


class _RawData(_Raw):
    gstin: Gstin
    rtnprd: str
    docdata: _RawDocData


class _RawGstr2b(_Raw):
    data: _RawData


def read_gstr2b(text: str | bytes, client: Client, period: str) -> list[TwoBEntry]:
    """Parse a GSTR-2B JSON file and check it belongs to this client and period."""
    try:
        # parse_float=Decimal: amounts never pass through a binary float.
        document = _RawGstr2b.model_validate(json.loads(text, parse_float=Decimal))
    except (ValidationError, ValueError) as exc:
        raise IngestError(f"GSTR-2B: {exc}") from exc

    data = document.data
    if data.gstin != client.gstin:
        raise IngestError(f"GSTR-2B is for {data.gstin}, not {client.client_id} ({client.gstin})")
    if data.rtnprd != to_return_period(period):
        raise IngestError(f"GSTR-2B is for return period {data.rtnprd}, not {period}")

    try:
        return [
            _to_entry(supplier, invoice, client, period)
            for supplier in data.docdata.b2b
            for invoice in supplier.inv
        ]
    except (ValidationError, ValueError) as exc:
        raise IngestError(f"GSTR-2B: {exc}") from exc


def _to_entry(
    supplier: _RawSupplier, invoice: _RawInvoice, client: Client, period: str
) -> TwoBEntry:
    itc_available = invoice.itcavl == ITC_AVAILABLE
    return TwoBEntry(
        client_id=client.client_id,
        period=period,
        supplier_gstin=supplier.ctin,
        supplier_name=supplier.trdnm,
        supplier_period=from_return_period(supplier.supprd),
        supplier_filing_date=supplier.supfildt,
        invoice_no=invoice.inum,
        invoice_date=invoice.dt,
        place_of_supply=invoice.pos,
        itc_available=itc_available,
        itc_unavailable_reason=None if itc_available else (invoice.rsn or None),
        taxable_value=invoice.txval,
        cgst=invoice.cgst,
        sgst=invoice.sgst,
        igst=invoice.igst,
        cess=invoice.cess,
        total=invoice.val,
    )


# --- Writing (used by the data generator) ------------------------------------


def write_purchase_register(invoices: Iterable[BookInvoice]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(PURCHASE_REGISTER_COLUMNS)
    for invoice in invoices:
        row = invoice.model_dump(mode="json")
        row["voucher_date"] = format_date(invoice.voucher_date)
        row["supplier_invoice_date"] = format_date(invoice.supplier_invoice_date)
        writer.writerow(row[column] for column in PURCHASE_REGISTER_COLUMNS)
    return buffer.getvalue()


def write_gstr2b(
    client: Client,
    period: str,
    generated_on: date,
    entries: Iterable[TwoBEntry],
) -> str:
    """Render entries in the portal's JSON shape. Suppliers appear in first-seen order."""
    suppliers: dict[tuple[str, str, date | None], list[dict[str, Any]]] = {}
    names: dict[str, str] = {}
    for entry in entries:
        key = (entry.supplier_gstin, entry.supplier_period, entry.supplier_filing_date)
        names[entry.supplier_gstin] = entry.supplier_name
        suppliers.setdefault(key, []).append(_invoice_json(entry))

    document = {
        "data": {
            "gstin": client.gstin,
            "rtnprd": to_return_period(period),
            "gendt": format_date(generated_on),
            "docdata": {
                "b2b": [
                    {
                        "ctin": gstin,
                        "trdnm": names[gstin],
                        "supprd": to_return_period(supplier_period),
                        "supfildt": format_date(filed_on) if filed_on else "",
                        "inv": invoices,
                    }
                    for (gstin, supplier_period, filed_on), invoices in suppliers.items()
                ]
            },
        }
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _invoice_json(entry: TwoBEntry) -> dict[str, Any]:
    return {
        "inum": entry.invoice_no,
        "dt": format_date(entry.invoice_date),
        "val": _json_number(entry.total),
        "typ": "R",
        "pos": entry.place_of_supply,
        "rev": "N",
        "itcavl": ITC_AVAILABLE if entry.itc_available else ITC_UNAVAILABLE,
        "rsn": entry.itc_unavailable_reason or "",
        "txval": _json_number(entry.taxable_value),
        "igst": _json_number(entry.igst),
        "cgst": _json_number(entry.cgst),
        "sgst": _json_number(entry.sgst),
        "cess": _json_number(entry.cess),
    }


def _json_number(amount: Decimal) -> float:
    """The portal format uses JSON numbers.

    Exact here: a 2-decimal amount below 10^13 has at most 15 significant
    digits, so its shortest float repr is the same decimal, and readers parse it
    back with `parse_float=Decimal`.
    """
    return float(amount)
