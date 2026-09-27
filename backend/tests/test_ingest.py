import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from backend.app.domain.entities import Client
from backend.app.domain.gstin import make_gstin
from backend.app.ingest import (
    PURCHASE_REGISTER_COLUMNS,
    IngestError,
    read_gstr2b,
    read_purchase_register,
)

CLIENT = Client(
    client_id="C01",
    name="Sri Balaji Textiles",
    gstin=make_gstin("36", "ABKFS4821M"),
    business_type="Textile trader",
)
SUPPLIER = make_gstin("36", "AAJFK4410L")
HEADER = ",".join(PURCHASE_REGISTER_COLUMNS)
ROW = (
    f"08-03-2026,PUR/0001,KL-889,07-03-2026,Krishna Logistics,{SUPPLIER},36,9967,"
    "25000.00,2250.00,2250.00,0.00,0.00,29500.00"
)


def gstr2b(**overrides: Any) -> str:
    invoice = {
        "inum": "KL889", "dt": "07-03-2026", "val": 29500.00, "typ": "R", "pos": "36",
        "rev": "N", "itcavl": "Y", "rsn": "", "txval": 25000.00,
        "igst": 0, "cgst": 2250.00, "sgst": 2250.00, "cess": 0,
    } | overrides  # fmt: skip
    return json.dumps(
        {
            "data": {
                "gstin": CLIENT.gstin,
                "rtnprd": "032026",
                "gendt": "14-04-2026",
                "docdata": {
                    "b2b": [
                        {
                            "ctin": SUPPLIER,
                            "trdnm": "KRISHNA LOGISTICS",
                            "supprd": "032026",
                            "supfildt": "11-04-2026",
                            "inv": [invoice],
                        }
                    ]
                },
            }
        }
    )


def test_reads_purchase_register_row() -> None:
    (invoice,) = read_purchase_register(f"{HEADER}\n{ROW}\n", CLIENT, "2026-03")
    assert invoice.supplier_invoice_no == "KL-889"
    assert invoice.voucher_date == date(2026, 3, 8)
    assert invoice.total == Decimal("29500.00")
    assert invoice.period == "2026-03"


def test_rejects_wrong_columns() -> None:
    with pytest.raises(IngestError, match="columns"):
        read_purchase_register("date,amount\n01-03-2026,100\n", CLIENT, "2026-03")


def test_reports_the_bad_line() -> None:
    bad = ROW.replace(SUPPLIER, "36AAJFK4410L1ZX")
    with pytest.raises(IngestError, match="line 3"):
        read_purchase_register(f"{HEADER}\n{ROW}\n{bad}\n", CLIENT, "2026-03")


def test_reads_gstr2b_entry() -> None:
    (entry,) = read_gstr2b(gstr2b(), CLIENT, "2026-03")
    assert entry.invoice_no == "KL889"
    assert entry.total == Decimal("29500.00")
    assert entry.supplier_period == "2026-03"
    assert entry.supplier_filing_date == date(2026, 4, 11)
    assert entry.itc_available


def test_reads_itc_unavailable_with_reason() -> None:
    (entry,) = read_gstr2b(gstr2b(itcavl="N", rsn="Cancelled"), CLIENT, "2026-03")
    assert not entry.itc_available
    assert entry.itc_unavailable_reason == "Cancelled"


def test_amounts_never_become_floats() -> None:
    (entry,) = read_gstr2b(gstr2b(val=0.1 + 0.2), CLIENT, "2026-03")
    assert entry.total == Decimal("0.30")


def test_rejects_wrong_period() -> None:
    with pytest.raises(IngestError, match="return period"):
        read_gstr2b(gstr2b(), CLIENT, "2026-04")


def test_rejects_other_clients_2b() -> None:
    other = CLIENT.model_copy(update={"gstin": make_gstin("36", "AAQFS7730K")})
    with pytest.raises(IngestError, match="is for"):
        read_gstr2b(gstr2b(), other, "2026-03")


def test_rejects_reverse_charge() -> None:
    with pytest.raises(IngestError):
        read_gstr2b(gstr2b(rev="Y"), CLIENT, "2026-03")


def test_rejects_malformed_json() -> None:
    with pytest.raises(IngestError):
        read_gstr2b("{not json", CLIENT, "2026-03")
