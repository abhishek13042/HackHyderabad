"""SPEC-02 acceptance criteria for the synthetic data generator."""

import hashlib
from collections import Counter
from functools import cache
from pathlib import Path

import pytest

from backend.app.domain.enums import Action, ExceptionType, Flag, RootCause
from backend.app.domain.gstin import is_valid_gstin
from backend.app.domain.policy import is_action_allowed
from backend.app.ingest import read_gstr2b, read_purchase_register
from backend.datagen.build import Dataset, build_dataset, typo_gstin
from backend.datagen.cast import CLIENTS, PERIODS, VENDORS, Treatment
from backend.datagen.ground_truth import LABELS, GroundTruthEntry, forbidden_terms
from backend.datagen.write import GSTR2B_FILE, PURCHASE_REGISTER_FILE, write_dataset

SEED = 42
VENDOR_BY_KEY = {vendor.key: vendor for vendor in VENDORS}


@cache
def dataset() -> Dataset:
    return build_dataset(SEED)


def entry(vendor_key: str, client_id: str, period: str) -> GroundTruthEntry:
    gstin = VENDOR_BY_KEY[vendor_key].gstin
    (match,) = (
        e
        for e in dataset().ground_truth
        if e.group_key.vendor_gstin == gstin
        and e.group_key.client_id == client_id
        and e.group_key.period == period
    )
    return match


def digest(folder: Path) -> dict[str, str]:
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


# --- AC-02-1: deterministic --------------------------------------------------


def test_same_seed_gives_byte_identical_files(tmp_path: Path) -> None:
    write_dataset(build_dataset(SEED), tmp_path / "a")
    write_dataset(build_dataset(SEED), tmp_path / "b")
    assert digest(tmp_path / "a") == digest(tmp_path / "b")


def test_different_seed_changes_amounts_but_not_groups() -> None:
    other = build_dataset(SEED + 1)
    assert other.books != dataset().books
    assert [e.group_key for e in other.ground_truth] == [
        e.group_key for e in dataset().ground_truth
    ]


def test_writes_expected_layout(tmp_path: Path) -> None:
    write_dataset(dataset(), tmp_path)
    expected = {"firm.json", "vendors.json", "ground_truth.json"} | {
        f"{client.client_id}/{period}/{name}"
        for client in CLIENTS
        for period in PERIODS
        for name in (PURCHASE_REGISTER_FILE, GSTR2B_FILE)
    }
    assert set(digest(tmp_path)) == expected


# --- AC-02-2: GSTINs ---------------------------------------------------------


def test_all_gstins_are_valid() -> None:
    gstins = [client.gstin for client in CLIENTS] + [vendor.gstin for vendor in VENDORS]
    assert all(is_valid_gstin(gstin) for gstin in gstins)
    assert len(set(gstins)) == len(gstins)


def test_books_typo_gstin_is_valid_but_unknown() -> None:
    known = {vendor.gstin for vendor in VENDORS}
    booked = {
        invoice.supplier_gstin for invoices in dataset().books.values() for invoice in invoices
    }
    typos = booked - known
    assert typos == {typo_gstin(VENDOR_BY_KEY["venkateswara_components"])}
    assert all(is_valid_gstin(typo) for typo in typos)


# --- AC-02-3 (generator side): planted behaviour ⇔ labels --------------------


def test_every_label_has_a_group_and_vice_versa() -> None:
    assert len(dataset().ground_truth) == len(LABELS) == 37


def test_group_counts_per_type() -> None:
    counts = Counter(e.group_key.exception_type for e in dataset().ground_truth)
    assert counts == {
        ExceptionType.MISSING_IN_2B: 16,
        ExceptionType.AMOUNT_MISMATCH: 9,
        ExceptionType.MISSING_IN_BOOKS: 4,
        ExceptionType.TAX_HEAD_MISMATCH: 4,
        ExceptionType.GSTIN_MISMATCH: 2,
        ExceptionType.ITC_INELIGIBLE: 2,
    }


def test_late_invoices_arrive_once_in_the_next_2b() -> None:
    reddy = VENDOR_BY_KEY["reddy_steels"]
    jan_bills = {b.number for b in dataset().bills if b.vendor == reddy and b.period == PERIODS[0]}
    feb_2b = [e for e in dataset().twob[("C01", PERIODS[1])] if e.supplier_gstin == reddy.gstin]
    assert len(feb_2b) == len(jan_bills)
    assert all(e.supplier_period == PERIODS[0] for e in feb_2b)
    later = [
        e
        for period in PERIODS[2:]
        for e in dataset().twob[("C01", period)]
        if e.supplier_gstin == reddy.gstin
    ]
    assert len(later) == sum(
        1 for b in dataset().bills if b.vendor == reddy and b.period == PERIODS[1]
    )  # only Feb's bills turn up (in March); from March on, Reddy stops filing


def test_mostly_clean_matches() -> None:
    """R3: roughly 85% of a client-month's invoices match cleanly."""
    months = Counter((b.client.client_id, b.period) for b in dataset().bills)
    clean = Counter(
        (b.client.client_id, b.period) for b in dataset().bills if b.treatment is Treatment.NORMAL
    )
    for month, total in months.items():
        assert clean[month] / total >= 0.75, month


# --- AC-02-4, AC-02-5: labels ------------------------------------------------


def test_actions_are_acceptable_and_allowed() -> None:
    for e in dataset().ground_truth:
        assert e.best_action in e.acceptable_actions
        assert e.accountant_action in e.acceptable_actions
        assert all(is_action_allowed(e.group_key.exception_type, a) for a in e.acceptable_actions)


def test_notes_never_give_the_game_away() -> None:
    for e in dataset().ground_truth:
        assert forbidden_terms(e.accountant_note) == []


@pytest.mark.parametrize(
    "note", ["This is a test.", "planted vendor", "Synthetic data", "LATE_FILER_CONSISTENT"]
)
def test_forbidden_terms_are_detected(note: str) -> None:
    assert forbidden_terms(note)


def test_forbidden_words_match_whole_words_only() -> None:
    assert forbidden_terms("the latest 2B") == []


def test_key_story_cells() -> None:
    drift = entry("reddy_steels", "C01", "2026-04")
    assert drift.best_action is Action.CHASE_VENDOR
    assert drift.accountant_action is Action.HOLD_PAYMENT
    assert drift.root_cause is RootCause.NOT_FILED
    assert Flag.PATTERN_DRIFT in drift.flags

    assert entry("reddy_steels", "C01", "2026-03").best_action is Action.DEFER
    assert Flag.CROSS_CLIENT_RISK in entry("krishna_logistics", "C03", "2026-03").flags
    assert entry("deccan_power", "C03", "2026-04").best_action is Action.ESCALATE


def test_recurring_flag_needs_two_prior_periods() -> None:
    laxmi = [entry("laxmi_packaging", "C01", period) for period in PERIODS]
    assert [Flag.RECURRING_ISSUE in e.flags for e in laxmi] == [False, False, True, True]
    assert Flag.RECURRING_ISSUE not in entry("om_sai_enterprises", "C02", "2026-03").flags


# --- AC-02-6 (file side): files load through the ingest parsers --------------


def test_generated_files_parse_back_identically(tmp_path: Path) -> None:
    write_dataset(dataset(), tmp_path)
    for client in CLIENTS:
        for period in PERIODS:
            folder = tmp_path / client.client_id / period
            key = (client.client_id, period)
            books_text = (folder / PURCHASE_REGISTER_FILE).read_text(encoding="utf-8")
            twob_text = (folder / GSTR2B_FILE).read_text(encoding="utf-8")
            assert read_purchase_register(books_text, client, period) == list(dataset().books[key])
            assert read_gstr2b(twob_text, client, period) == list(dataset().twob[key])
