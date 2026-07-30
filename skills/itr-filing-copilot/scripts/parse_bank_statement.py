#!/usr/bin/env python3
"""
Read a bank statement for the two things a return needs from it.

Standard library only. Reads nothing but the files you name. No network.

    python3 parse_bank_statement.py hdfc.pdf kotak.pdf dcb.pdf
    python3 parse_bank_statement.py statement.pdf --summary
    python3 parse_bank_statement.py statement.pdf --credits-above 100000

A statement holds thousands of rows and a return needs two answers out of it:

  **How much interest was credited.** It goes in Schedule OS, and under the new
  regime there is no s.80TTA deduction to soften it. AIS reports it under
  SFT-016(SB), but only from banks that filed, so a statement is the only
  complete source.

  **Which credits need explaining.** A large credit is not income by itself — a
  gift from a relative is outside the charge entirely, a loan is not income, a
  transfer between your own accounts is nothing at all. But every one of them
  has to be *identified* before the return is defensible, and the ones nobody
  can explain are where a s.68 or s.56(2)(x) problem starts.

It does not categorise spending, and it does not decide what a credit was. It
finds the rows that need a human answer and asks for one.

Layouts differ by bank, so nothing here is positional: the header row is found
by its labels, and any statement whose columns cannot be identified is reported
rather than guessed at. `--text` dumps the extracted text for an unknown layout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_pdf import PdfError, extract_pages  # noqa: E402
from pdf_crypt import CryptError, resolve_password  # noqa: E402
from redact import safe_name  # noqa: E402

AMOUNT = re.compile(r"-?\d{1,3}(?:,\d{2,3})*\.\d{2}|-?\d+\.\d{2}")
# Separators: HDFC writes 23.04.2025, Kotak 23-04-2025, ICICI 23/04/2025, and
# two-digit years turn up on all of them. The dot is not cosmetic. With only
# `-` and `/` accepted, a 58-page statement yielded two transaction rows — and
# worse, every dotted date also matched the amount pattern, so 23.04.2025 was
# read as an amount of ₹23.04. Both halves of that bug are fixed here: the
# separator below, and `mask_dates`, which removes dates from a line before any
# amount is read off it.
DATE_FORMS = [
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[-\s/.]?([A-Za-z]{3})[-\s/.]?(\d{4})\b"), "dMy"),
    (re.compile(r"\b(\d{1,2})[-\s/.]?([A-Za-z]{3})[-\s/.]?(\d{2})\b"), "dMy2"),
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2})\b"), "dmy2"),
]
# Everything the forms above can match, for masking. Ordered longest-first so a
# four-digit year is consumed before the two-digit form can take a bite of it.
DATE_ANY = re.compile(
    r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}[-\s/.]?[A-Za-z]{3}[-\s/.]?\d{4}\b"
    r"|\b\d{1,2}[-\s/.]?[A-Za-z]{3}[-\s/.]?\d{2}\b"
    r"|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2}\b")
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")

# Interest credited by the bank. Deliberately narrow: a UPI payment to a person
# named "Interest" should not become taxable income.
INTEREST = re.compile(
    r"\b(credit\s*interest|int\.?\s*(?:credit|pd|paid)|interest\s*(?:credit|paid|earned)"
    r"|saving\s*int|sb\s*int|int\s*on\s*(?:sb|saving)|quarterly\s*interest"
    r"|interest\s*capitalis)", re.I)
# Some banks narrate a quarterly interest credit as the single word INTEREST,
# with no counterparty and nothing else on the row. The pattern above misses it
# on purpose — a bare word match would turn a UPI payment to a person named
# Interest into taxable income. This one is safe because it requires the whole
# narration to *be* that word: a counterparty, a channel (UPI, NEFT, IMPS) or a
# reference number anywhere on the row disqualifies it. [observed] on a real
# statement where four quarterly credits were narrated exactly this way and none
# of them was counted.
INTEREST_BARE = re.compile(
    r"^(?:cr|credit)?\s*interest\s*(?:credit|paid|cr|capitalised|capitalized)?$",
    re.I)

# Interest the bank charged you. Never income.
INTEREST_DEBIT = re.compile(r"\b(int\.?\s*(?:coll|debit|charged)|debit\s*interest|"
                            r"overdraft\s*int|loan\s*int)", re.I)

# Credits that explain themselves, so they are not put to the taxpayer.
SELF_EVIDENT = re.compile(
    r"\b(reversal|refund|cashback|failed|returned|chargeback|auto\s*sweep|"
    r"sweep\s*(?:in|out)|closure\s*proceed|maturity\s*of|redemption\s*of\s*fd|"
    r"td\s*closure|self|own\s*a/c)\b", re.I)

# Brought-forward and carried-forward lines. They anchor the running balance and
# must be read, but they are not transactions: an earlier version offered a
# closing balance of ₹81,550 as a receipt needing explanation.
BALANCE_LINE = re.compile(
    r"\b(opening|closing|brought|carried)\s*(balance|forward)?\b|\bb/?f\b|\bc/?f\b",
    re.I)

QUARTERS = [("upto 15 Jun", (4, 1), (6, 15)), ("16 Jun to 15 Sep", (6, 16), (9, 15)),
            ("16 Sep to 15 Dec", (9, 16), (12, 15)), ("16 Dec to 15 Mar", (12, 16), (3, 15)),
            ("16 Mar to 31 Mar", (3, 16), (3, 31))]


def parse_date(text: str):
    for pattern, kind in DATE_FORMS:
        for m in pattern.finditer(text):
            try:
                if kind == "dmy":
                    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                elif kind == "dmy2":
                    d, mo, y = int(m.group(1)), int(m.group(2)), 2000 + int(m.group(3))
                elif kind in ("dMy", "dMy2"):
                    d = int(m.group(1))
                    mo = MONTHS[m.group(2)[:3].lower()]
                    y = int(m.group(3))
                    y = y + 2000 if kind == "dMy2" else y
                else:
                    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 1 <= mo <= 12 and 1 <= d <= 31 and 2000 <= y <= 2100:
                    return f"{y:04d}-{mo:02d}-{d:02d}"
            except (ValueError, KeyError):
                continue
    return None


def mask_dates(line: str) -> str:
    """Blank out every date so no part of one can be read as an amount."""
    return DATE_ANY.sub(lambda m: " " * len(m.group(0)), line)


def financial_year_of(iso: str) -> str:
    """India's year runs 1 April to 31 March. A statement that crosses 31 March
    carries interest belonging to two different returns."""
    y, m = int(iso[:4]), int(iso[5:7])
    start = y if m >= 4 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


def looks_like_bare_interest(line: str) -> bool:
    letters = re.sub(r"[^A-Za-z ]", " ", line)
    return bool(INTEREST_BARE.match(re.sub(r"\s+", " ", letters).strip()))


def quarter_of(iso: str) -> str:
    mo, d = int(iso[5:7]), int(iso[8:10])
    for label, (m1, d1), (m2, d2) in QUARTERS:
        if (m1, d1) <= (m2, d2):
            if (m1, d1) <= (mo, d) <= (m2, d2):
                return label
        elif (mo, d) >= (m1, d1) or (mo, d) <= (m2, d2):
            return label
    return "unclassified"


def amounts(line: str) -> list[float]:
    out = []
    for token in AMOUNT.findall(line):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            pass
    return out


# The IFSC prefix is the bank, definitively. Reading the name out of the text
# instead gets it wrong the moment a transaction narration mentions another
# bank — a NEFT to an ICICI account made a DCB statement read as ICICI.
IFSC_BANKS = {
    "HDFC": "HDFC", "ICIC": "ICICI", "SBIN": "SBI", "KKBK": "Kotak",
    "DCBL": "DCB", "UTIB": "Axis", "INDB": "IndusInd", "YESB": "Yes",
    "IDFB": "IDFC First", "BARB": "Bank of Baroda", "PUNB": "PNB",
    "CNRB": "Canara", "UBIN": "Union Bank", "FDRL": "Federal",
    "IOBA": "Indian Overseas", "MAHB": "Bank of Maharashtra",
    "CBIN": "Central Bank", "IDIB": "Indian Bank", "PSIB": "Punjab & Sind",
    "UCBA": "UCO", "BKID": "Bank of India", "AUBL": "AU Small Finance",
    "RATN": "RBL", "KARB": "Karnataka", "SIBL": "South Indian",
    "TMBL": "Tamilnad Mercantile", "CSBK": "CSB", "DBSS": "DBS",
    "SCBL": "Standard Chartered", "CITI": "Citi", "HSBC": "HSBC",
}


def detect_bank(text: str) -> str:
    """Prefer the account's own IFSC over any name printed on the page."""
    ifsc = IFSC.search(text[:6000]) or IFSC.search(text)
    if ifsc:
        name = IFSC_BANKS.get(ifsc.group(0)[:4].upper())
        if name:
            return name
        return f"unrecognised IFSC prefix {ifsc.group(0)[:4]}"
    head = re.sub(r"\s+", "", text[:2500]).lower()
    for needle, name in (("hdfcbank", "HDFC"), ("icicibank", "ICICI"),
                         ("statebankofindia", "SBI"), ("kotakmahindra", "Kotak"),
                         ("dcbbank", "DCB"), ("axisbank", "Axis")):
        if needle in head:
            return name
    return "unknown"


def transaction_rows(text: str) -> list[dict]:
    """Every line that carries a date and at least one amount.

    The amounts are read from the line with its dates masked out, so a dotted
    date can never be counted as a figure."""
    rows: list[dict] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if len(line) < 12:
            continue
        iso = parse_date(line)
        if not iso:
            continue
        values = amounts(mask_dates(line))
        if not values:
            continue
        rows.append({"date": iso, "values": values, "line": line,
                     "movement": values[-2] if len(values) >= 2 else values[0],
                     "direction": "unknown"})
    return rows


def balance_order(rows: list[dict]) -> tuple[int | None, float]:
    """Decide whether the last figure on each row is a running balance, and
    which way the statement runs.

    A transaction row ends with the balance after the transaction. So for two
    consecutive rows the change in that last figure is the movement, signed:
    positive is money in. The test that this is really a balance column is that
    the change equals one of the other figures printed on the row. Where that
    holds across the statement the direction of every row is known; where it
    does not, the column is something else and nothing is assumed.

    Statements come in both orders. Kotak prints oldest first, some credit-card
    and app exports print newest first, and reading a reversed statement as
    chronological inverts every credit into a debit. Both orders are scored and
    the better one wins; a tie means neither, which is a refusal."""
    # A brought-forward line carries only the balance, no movement. It cannot
    # be signed itself, but it is the anchor the first real transaction steps
    # from — without it the opening row of every statement is undetermined.
    usable = [r for r in rows if r["values"]]
    if len(usable) < 4:
        return None, 0.0

    def score(seq: list[dict]) -> float:
        matched = steps = 0
        for prev, cur in zip(seq, seq[1:]):
            if len(cur["values"]) < 2:
                continue
            delta = round(cur["values"][-1] - prev["values"][-1], 2)
            steps += 1
            if any(abs(abs(delta) - v) <= 0.01 for v in cur["values"][:-1]):
                matched += 1
        return matched / steps if steps else 0.0

    forward, backward = score(usable), score(usable[::-1])
    best, order = (forward, 1) if forward >= backward else (backward, -1)
    # Below two thirds the "balance" is not a balance. A statement whose amount
    # column happens to drift upward would otherwise score around a half.
    if best < 0.66 or abs(forward - backward) < 0.02:
        return None, best
    return order, best


def apply_direction(rows: list[dict], order: int | None) -> None:
    """Sign each row's movement from the step in the running balance."""
    if order is None:
        return
    seq = [r for r in rows if r["values"]]
    if order == -1:
        seq = seq[::-1]
    for prev, cur in zip(seq, seq[1:]):
        if len(cur["values"]) < 2:
            continue
        delta = round(cur["values"][-1] - prev["values"][-1], 2)
        if delta == 0:
            continue
        printed = [v for v in cur["values"][:-1] if abs(abs(delta) - v) <= 0.01]
        if not printed:
            # A page break, a brought-forward line or a row this reader split
            # wrongly. Leaving it "unknown" keeps it out of the credit list
            # instead of reporting a figure nothing corroborates.
            continue
        cur["direction"] = "credit" if delta > 0 else "debit"
        cur["movement"] = abs(delta)


def balance_integrity(rows: list[dict], order: int | None) -> dict:
    """Does the first balance plus every movement reach the last balance?

    This is the only check on this statement that can notice rows that were
    never read. Interest looks plausible when half the pages were skipped, and
    a credit list looks plausible when it is missing entries — but the running
    balance cannot be reconciled unless every row between the two ends was
    understood. A 58-page statement that yielded two rows would have failed this
    instantly; nothing was watching.

    It is a check, not a correction: it says whether the rows add up, and by how
    much they do not."""
    usable = [r for r in rows if r["values"]]
    if order is None or len(usable) < 3:
        return {"checked": False,
                "why": "the running-balance column was not identified"}
    seq = usable if order == 1 else usable[::-1]
    first, last = seq[0], seq[-1]
    opening, closing = first["values"][-1], last["values"][-1]

    # seq[0] and seq[-1] are the first and last rows *that were read*, which is
    # not the same as the statement's opening and closing balances. If the
    # reader dropped rows at either end, the identity below still holds among
    # the survivors and would have reported that nothing was missed. It can only
    # say that when both ends are anchored on a brought-forward or
    # carried-forward line, which is a claim the statement itself makes.
    anchored_open = bool(BALANCE_LINE.search(first["line"]))
    anchored_close = bool(BALANCE_LINE.search(last["line"]))

    movement = 0.0
    unsigned = 0
    for row in seq[1:]:
        if row["direction"] == "credit":
            movement += row["movement"]
        elif row["direction"] == "debit":
            movement -= row["movement"]
        else:
            unsigned += 1

    expected = round(opening + movement, 2)
    difference = round(closing - expected, 2)
    return {
        "checked": True,
        "first_balance_read": opening,
        "last_balance_read": closing,
        "anchored_on_a_brought_forward_line": anchored_open,
        "anchored_on_a_carried_forward_line": anchored_close,
        "covers_the_whole_statement": anchored_open and anchored_close,
        "net_movement_of_rows_read": round(movement, 2),
        "unexplained": difference,
        "rows_without_a_direction": unsigned,
        "reconciles": abs(difference) <= 0.01,
    }


def parse(path: str, credit_threshold: float,
          password: str | None = None,
          financial_year: str | None = None) -> dict:
    pages = extract_pages(path, password)
    text = "\n".join(pages)
    bank = detect_bank(text)

    ifsc = IFSC.search(text)
    period = None
    m = re.search(r"(\d{2}[-/ ][A-Za-z0-9]{2,3}[-/ ]\d{4})\s*(?:To|to|-|–)\s*"
                  r"(\d{2}[-/ ][A-Za-z0-9]{2,3}[-/ ]\d{4})", text)
    if m:
        period = {"from": parse_date(m.group(1)), "to": parse_date(m.group(2))}

    rows = transaction_rows(text)
    order, agreement = balance_order(rows)
    apply_direction(rows, order)

    interest: list[dict] = []
    credits: list[dict] = []
    unclassified: list[dict] = []

    for row in rows:
        line, iso = row["line"], row["date"]
        label = re.sub(r"[\d,./]+", " ", line)
        label = re.sub(r"\s+", " ", label).strip()[:90]
        movement = row["movement"]

        matched_interest = (INTEREST.search(line)
                            or looks_like_bare_interest(line))
        if matched_interest and not INTEREST_DEBIT.search(line):
            # The narration says interest was paid; the balance says which way
            # the money went. A row whose balance fell is not interest income
            # however it is worded, and an unreadable balance column is not a
            # reason to drop an interest row that the wording already identified.
            if row["direction"] == "debit":
                row["rejected"] = "narration says interest, balance says debit"
                continue
            interest.append({"date": iso, "amount": movement,
                             "financial_year": financial_year_of(iso),
                             "quarter": quarter_of(iso), "narration": label,
                             "direction": row["direction"]})
            continue

        # A credit raises the balance. That is now decided from the running
        # balance rather than from column position, so a deposit is told from a
        # withdrawal on any layout. Where the balance column could not be
        # identified the row is not offered as a credit at all — the earlier
        # version offered every large figure, debits included.
        if row["direction"] == "credit" and movement >= credit_threshold:
            credits.append({"date": iso, "amount": movement,
                            "narration": label,
                            "self_evident": bool(SELF_EVIDENT.search(line))})
        elif (row["direction"] == "unknown" and order is not None
                and movement >= credit_threshold
                and not BALANCE_LINE.search(line)):
            # The first row of a statement has no previous balance to step from,
            # and a page break can lose one. Such a row is neither reported as a
            # credit nor quietly dropped: it is listed as undetermined, because a
            # large receipt that nobody looked at is the whole risk here.
            unclassified.append({"date": iso, "amount": movement,
                                 "narration": label})

    # A statement that crosses 31 March carries interest belonging to two
    # different returns. Nothing here decides which one you want: the split is
    # reported, and --financial-year selects. Summing across the boundary is how
    # a quarter of somebody else's year ends up in Schedule OS.
    by_year: dict[str, float] = defaultdict(float)
    for entry in interest:
        by_year[entry["financial_year"]] += entry["amount"]
    in_year = [e for e in interest
               if financial_year is None or e["financial_year"] == financial_year]

    by_quarter: dict[str, float] = defaultdict(float)
    for entry in in_year:
        by_quarter[entry["quarter"]] += entry["amount"]

    integrity = balance_integrity(rows, order)
    directed = sum(1 for r in rows if r["direction"] in ("credit", "debit"))
    if not rows:
        confidence = "no transaction rows read"
    elif order is None:
        confidence = ("balance column not identified — direction unknown, so no "
                      "credit is offered for review")
    else:
        confidence = (f"direction read from the running balance on {directed} of "
                      f"{len(rows)} rows ({agreement:.0%} of balance steps match a "
                      f"figure printed on the row); statement is in "
                      f"{'chronological' if order == 1 else 'reverse-chronological'} "
                      f"order")

    return {
        "file": safe_name(path),
        "bank": bank,
        "ifsc": ifsc.group(0) if ifsc else None,
        "period": period,
        "pages": len(pages),
        "transaction_rows_read": len(rows),
        "interest_credited": {
            "total": round(sum(e["amount"] for e in in_year), 2),
            "count": len(in_year),
            "financial_year_selected": financial_year,
            "by_financial_year": {k: round(v, 2) for k, v in sorted(by_year.items())},
            "by_quarter": {k: round(v, 2) for k, v in sorted(by_quarter.items())},
            "entries": in_year,
        },
        "large_credits": [c for c in credits if not c["self_evident"]],
        "large_credits_self_evident": [c for c in credits if c["self_evident"]],
        "large_amounts_direction_unknown": unclassified,
        "layout_confidence": confidence,
        "direction_from_balance": order is not None,
        "balance_integrity": integrity,
    }


def report(results: list[dict], threshold: float,
           financial_year: str | None = None) -> dict:
    checks, flags = [], []
    for r in results:
        years = r["interest_credited"]["by_financial_year"]
        if len(years) > 1 and financial_year is None:
            flags.append(
                f"{r['file']}: interest was credited in more than one financial "
                f"year — {', '.join(f'{k} {v:,.2f}' for k, v in years.items())} — "
                "and the total above adds them together. India's year runs 1 "
                "April to 31 March, so a statement that crosses that date holds "
                "interest belonging to two different returns. Re-run with "
                "--financial-year 2025-26 (for AY 2026-27) to take only one.")
        elif financial_year and financial_year not in years and years:
            flags.append(
                f"{r['file']}: no interest at all was credited in {financial_year}; "
                f"what the statement holds is {', '.join(years)}. Either this is "
                "the wrong statement for the year being filed, or the period it "
                "covers is too short.")
    total_interest = round(sum(r["interest_credited"]["total"] for r in results), 2)

    if total_interest:
        checks.append(
            f"Interest credited across {len(results)} account(s): {total_interest:,.2f}. "
            "It belongs in Schedule OS. Under the new regime there is no s.80TTA "
            "deduction against it, so the whole figure is taxable at slab rates.")
        checks.append(
            "Cross-check against AIS SFT-016(SB). AIS carries savings interest only "
            "from banks that reported, so a bank missing from AIS does not mean the "
            "interest was not earned. Where they differ, report the discrepancy "
            "without choosing either figure. If the AIS item is wrong, submit AIS "
            "feedback; if filing from the statement, retain the complete statement, "
            "feedback acknowledgement and a reconciliation working paper. A mismatch "
            "may draw a proposed s.143(1)(a) adjustment; respond with the evidence "
            "rather than declaring income that was not earned.")
    else:
        flags.append(
            "No interest credit was recognised in any statement. That is unusual "
            "for a savings account held all year. Check the narration wording with "
            "--text and open an issue with the phrasing, no amounts.")

    undetermined = [(r["file"], c) for r in results
                    for c in r["large_amounts_direction_unknown"]]
    if undetermined:
        flags.append(
            f"{len(undetermined)} row(s) at or above {threshold:,.0f} could not be "
            "signed from the running balance — the first row of a statement has "
            "no previous balance to step from, and a page break loses one. They "
            "are listed under large_amounts_direction_unknown. Open the statement "
            "at those dates and check each one by eye; a credit hiding there is "
            "exactly what this script exists to surface.")

    unexplained = [(r["file"], c) for r in results for c in r["large_credits"]]
    if unexplained:
        flags.append(
            f"{len(unexplained)} credit(s) at or above {threshold:,.0f} need an "
            "explanation before this return is defensible. A large credit is not "
            "income by itself — a gift from a relative is outside the charge, a "
            "loan is not income, a transfer between your own accounts is nothing "
            "at all. But an unexplained credit is where a s.68 addition starts, "
            "and a gift from a non-relative above 50,000 is taxable in full under "
            "s.56(2)(x), not just on the excess. Ask about each one and record the "
            "answer in your working papers.")

    for r in results:
        check = r["balance_integrity"]
        if check.get("checked") and check["reconciles"]:
            whole = check["covers_the_whole_statement"]
            checks.append(
                f"{r['file']}: {check['first_balance_read']:,.2f} plus every "
                f"movement read reaches {check['last_balance_read']:,.2f} exactly"
                + (", and both ends sit on the statement's own brought-forward "
                   "and carried-forward lines, so no row was missed anywhere in "
                   "it. That is the only evidence available for that — interest "
                   "and credits both look plausible when half a statement was "
                   "skipped."
                   if whole else
                   ". Those are the first and last rows *read*, not the "
                   "statement's own opening and closing balances, which this "
                   "reader could not find. So nothing was missed between them — "
                   "rows dropped before the first or after the last would not "
                   "show up here at all. Check the period and the row count "
                   "against the statement by eye."))
        elif check.get("checked"):
            flags.append(
                f"{r['file']}: {check['first_balance_read']:,.2f} plus the "
                f"movements read comes to "
                f"{check['first_balance_read'] + check['net_movement_of_rows_read']:,.2f}, "
                f"but the last balance read is "
                f"{check['last_balance_read']:,.2f} — {abs(check['unexplained']):,.2f} "
                f"unaccounted for across "
                f"{check['rows_without_a_direction']} row(s) whose direction could "
                "not be read. Rows were missed, so treat the interest figure as a "
                "floor, not a total, and run --text to see what the reader made of "
                "the layout.")

    for r in results:
        if not r["direction_from_balance"] and r["transaction_rows_read"]:
            flags.append(
                f"{r['file']}: the running-balance column could not be "
                "identified, so a deposit cannot be told from a withdrawal and "
                "no credit was offered for review. The interest figure is still "
                "usable — it comes from the narration, not the direction. Run "
                "--text and open an issue with the header row so the layout can "
                "be added.")
        if r["transaction_rows_read"] and r["pages"] > 3 and \
                r["transaction_rows_read"] < r["pages"] * 3:
            flags.append(
                f"{r['file']}: only {r['transaction_rows_read']} rows read from "
                f"{r['pages']} pages. That is too few — most of this statement was "
                "not understood, so treat the interest figure as incomplete. Run "
                "--text and open an issue with the header row.")
        if r["transaction_rows_read"] == 0:
            flags.append(
                f"{r['file']}: no transaction rows were read at all. If this is a "
                "scanned statement it has no text layer, and it must be treated as "
                "unreadable — never as an account with no transactions.")
    return {"checks": checks, "flags": flags,
            "total_interest_credited": total_interest}


def summarise(out: dict) -> str:
    """Print the interest, review counts, integrity result and every flag."""
    money = lambda value: f"₹{value:,.2f}"
    selected = {a["interest_credited"]["financial_year_selected"]
                for a in out["accounts"]
                if a["interest_credited"]["financial_year_selected"]}
    years = sorted({year for account in out["accounts"]
                    for year in account["interest_credited"]["by_financial_year"]})
    if len(selected) == 1:
        period = f"FY {next(iter(selected))}"
    elif len(years) == 1:
        period = f"FY {years[0]}"
    elif years:
        period = "all statement periods (" + ", ".join(f"FY {y}" for y in years) + ")"
    else:
        period = "statement period not identified"
    lines = [
        f"Interest credited — {period}: {money(out['total_interest_credited'])} "
        f"across {len(out['accounts'])} account(s)"
    ]
    for account in out["accounts"]:
        interest = account["interest_credited"]
        integrity = account["balance_integrity"]
        if integrity.get("checked"):
            balance = "reconciles" if integrity["reconciles"] else "DOES NOT reconcile"
        else:
            balance = "not checked"
        lines.extend([
            f"{account['file']}: {account['bank'] or 'bank unknown'}",
            f"  interest: {money(interest['total'])} across {interest['count']} credit(s)",
            f"  large credits needing explanation: {len(account['large_credits'])}",
            f"  transaction rows read: {account['transaction_rows_read']}",
            f"  balance integrity: {balance}",
        ])
    if out["flags"]:
        lines.extend(["", "Flags", *out["flags"]])
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--credits-above", type=float, default=50000,
                    help="report credits at or above this for explanation "
                         "(default 50,000, the s.56(2)(x) gift threshold)")
    ap.add_argument("--financial-year", metavar="YYYY-YY",
                    help="count only interest credited in this financial year, "
                         "e.g. 2025-26 for AY 2026-27. Without it, a statement "
                         "crossing 31 March contributes interest from both years")
    ap.add_argument("--text", action="store_true", help="dump the extracted text")
    ap.add_argument("--summary", action="store_true",
                    help="print the key figures and every flag as plain lines")
    ap.add_argument("--password", help="for a password-protected statement; "
                                       "banks vary, but PAN + ddmmyyyy and the "
                                       "customer ID are the common two")
    ap.add_argument("--password-stdin", action="store_true",
                    help="read the password from standard input instead, so it "
                         "never appears in argv or in shell history")
    ap.add_argument("--json", metavar="PATH")
    a = ap.parse_args(argv)

    if a.summary and a.text:
        print(json.dumps({
            "refused": "--summary and --text are two different stdout modes. "
                       "Use --summary for parsed figures or --text for the "
                       "extracted statement text."
        }, indent=2), file=sys.stderr)
        return 2

    try:
        password = resolve_password(a.password, a.password_stdin)
    except CryptError as e:
        print(json.dumps({"refused": str(e)}, indent=2), file=sys.stderr)
        return 2

    results = []
    for path in a.files:
        try:
            if a.text:
                print(f"----- {safe_name(path)} -----")
                print("\n".join(extract_pages(path, password)))
                continue
            results.append(parse(path, a.credits_above, password,
                                 a.financial_year))
        except PdfError as e:
            print(json.dumps({"refused": str(e),
                              "file": safe_name(path)}, indent=2),
                  file=sys.stderr)
            return 2
    if a.text:
        return 0

    out = {"accounts": results,
           **report(results, a.credits_above, a.financial_year),
           "disclaimer": "Read from the statements as given. It finds interest "
                         "and the credits that need explaining; it does not "
                         "decide what any credit was. Nothing here reproduces an "
                         "account number, but the source files do."}
    if a.summary:
        print(summarise(out))
    else:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
