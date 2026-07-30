#!/usr/bin/env python3
"""
Read the department's own documents: AIS, TIS, Form 26AS, Form 168, Form 16.

Standard library only. Reads nothing but the files you name. No network.

    python3 parse_tax_docs.py AIS.pdf TIS.pdf 26AS.pdf Form16.pdf
    python3 parse_tax_docs.py AIS.pdf --summary
    python3 parse_tax_docs.py AIS.pdf --json ais.json
    python3 parse_tax_docs.py unknown.pdf --text        # dump the text instead

These four documents are what a return is reconciled against, and every one of
them is a PDF laid out as a table. Reading them by eye is where transcription
errors come from, and reading them with a language model is where invented
figures come from.

What it produces is a tie-out, not a return: totals by information category,
TDS by deductor and section, and the differences between documents that a filer
has to explain before filing. Where two documents disagree it says so and does
not pick a winner.

Encrypted files
---------------
AIS, TIS and most Form 16s download encrypted. The password is the lowercase
PAN followed by the date of birth as ddmmyyyy. Pass it with --password and the
file is decrypted in memory as it is read; no plaintext copy is written.

One thing this cannot tell you
------------------------------
AIS silence is not evidence. A filer with a full year of equity disposals had
nothing at all reported under any SFT category. Always ask for the broker
statement separately, whatever AIS shows.
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

# Indian grouping (5,43,210) and plain (1660000.00) in one pattern. Matching
# the grouped form first with a 3-digit head split 1660000.00 into 166, 000
# and .00 — every large unpunctuated figure came out as three small ones.
MONEY = re.compile(r"-?\d+(?:,\d{2,3})*(?:\.\d+)?")
DATE = re.compile(r"\b(\d{2}/\d{2}/\d{4}|\d{2}-[A-Za-z]{3}-\d{4})\b")
PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
TAN = re.compile(r"\b[A-Z]{4}\d{5}[A-Z]\b")
# SFT codes carry a bracketed qualifier that decides the tax treatment:
# SFT-18-EMF is equity-oriented, SFT-18-OTU is not. Truncating the closing
# bracket loses exactly the character that matters.
INFO_CODE = re.compile(
    r"(SFT-\d{2,3}(?:-[A-Z]{2,3})?(?:\([A-Za-z]{1,3}\))?"
    r"|TDS-\d{3}[A-Z]{0,2}|TCS-\d{3}[A-Z]{0,2})")


def money(text: str):
    text = text.replace("₹", " ").strip()
    m = MONEY.findall(text)
    if not m:
        return None
    try:
        return float(m[-1].replace(",", ""))
    except ValueError:
        return None


def all_money(line: str) -> list[float]:
    out = []
    for token in MONEY.findall(line.replace("₹", " ")):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            pass
    return out


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------- detect

def detect(text: str) -> str:
    # The extractor preserves column positions, not word spacing, so a title
    # can arrive as "TaxpayerInformationSummary". Match without spaces.
    head = re.sub(r"\s+", "", text[:4000]).lower()
    if "taxpayerinformationsummary" in head:
        return "TIS"
    if "annualinformationstatement" in head:
        return "AIS"
    if "form168" in head or "annualtaxstatement" in head:
        return "26AS"
    if "annualtaxstatement" in head or "form26as" in head:
        return "26AS"
    if "formno.16" in head or "formno.16" in head:
        return "FORM16B" if "partb" in head else "FORM16A"
    if "intimation" in head and "143(1)" in head:
        return "INTIMATION"
    return "UNKNOWN"


def identity(text: str) -> dict:
    out = {}
    pan = PAN.search(text)
    if pan:
        out["pan_present"] = True       # never echoed; see the note in --help
    fy = re.search(r"(20\d{2})-(\d{2})", text)
    if fy:
        out["period"] = fy.group(0)
    return out


# ------------------------------------------------------------------------ TIS

TIS_CATEGORIES = {
    "salary": "Salary",
    "dividend": "Dividend",
    "interest from savings bank": "Interest — savings bank",
    "interest from deposit": "Interest — deposits",
    "interest from others": "Interest — others",
    "accumulated balance of pf": "PF withdrawal",
    "sale of securities": "Sale of securities and mutual-fund units",
    "purchase of securities": "Purchase of securities and mutual-fund units",
    "sale of immovable property": "Sale of immovable property",
    "purchase of immovable property": "Purchase of immovable property",
    "business receipts": "Business receipts",
    "rent received": "Rent received",
    "off market debit": "Off-market debit",
    "off market credit": "Off-market credit",
    "winnings from": "Winnings",
    "receipts from life insurance": "Life insurance receipts",
    "gst turnover": "GST turnover",
}


def parse_tis(pages: list[str]) -> dict:
    categories: dict[str, dict] = {}
    for line in "\n".join(pages).splitlines():
        flat = squash(line).lower()
        flat_nospace = flat.replace(" ", "")
        if not flat or flat.startswith("sr."):
            continue
        for needle, label in TIS_CATEGORIES.items():
            if needle.replace(" ", "") in flat_nospace:
                values = all_money(line)
                # A category line ends in processed-by-system and accepted-by-
                # taxpayer. The serial number at the start is not an amount.
                values = [v for v in values if v >= 1]
                if len(values) >= 2:
                    processed, accepted = values[-2], values[-1]
                elif values:
                    processed = accepted = values[-1]
                else:
                    continue
                prev = categories.get(label)
                if prev and prev["accepted_by_taxpayer"] >= accepted:
                    continue
                categories[label] = {"processed_by_system": processed,
                                     "accepted_by_taxpayer": accepted}
                break
    return {"categories": categories}


# ------------------------------------------------------------------------ AIS

AIS_PARTS = [
    ("part b1", "B1 — tax deducted or collected at source"),
    ("part b2", "B2 — SFT information"),
    ("part b3", "B3 — payment of taxes"),
    ("part b4", "B4 — demand and refund"),
    ("part b5", "B5 — other information"),
    ("part b6", "B6 — other information"),
    ("part b7", "B7 — other information"),
]


# Columns whose contents must never leave this script. AIS prints the account
# number a savings-interest figure was reported against, and that number is the
# single most sensitive field in the document.
REDACT_COLUMNS = re.compile(
    r"account\s*(number|no)|a/?c\s*(number|no)|\bpan\b|aadhaar|"
    r"mobile|e-?mail|address|client\s*id|folio|\bdp\s*id\b|demat|"
    r"customer\s*id|\buan\b", re.I)

# Page furniture. The reader lays text on a character grid by position, so a
# page footer can land on the same grid row as a transaction and be read as part
# of it — a download ID carrying the PAN ended up inside a security name.
FURNITURE = re.compile(
    r"(?:do)?wnload\s*ID\s*:\S*|(?:ge)?ner\s*ationDate\s*:\S*|"
    r"Generation\s*Date\s*:\S*|Page\s*\d+\s*of\s*\d+|IP\s*Address\s*:\S*",
    re.I)

# Nothing that identifies a person leaves a cell, whatever column it was found
# in. A layout quirk should not be the only thing standing between an account
# number and the output.
IDENTIFIER = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b|\d{9,}")

# A sub-table header introduces the rows underneath an information code. The
# summary header ("SR. NO. INFORMATION CODE ...") introduces the codes
# themselves and is handled separately.
SUMMARY_HEADER = re.compile(r"^sr\.?\s*no\.?\s+information\s+code", re.I)
# Matched against the squashed line, where runs of spaces are already gone —
# an earlier version required two spaces here and so never matched anything,
# which meant the column path never ran at all and every sub-table fell through
# to the positional fallback.
SUBTABLE_HEADER = re.compile(r"^sr\.?\s*(no\.?)?\b", re.I)

# A run of nine or more digits in a document that prints account numbers is an
# account number until proved otherwise. The fallback path used to emit them as
# amounts, which put four real account numbers in the JSON output.
LONG_DIGITS = re.compile(r"\d{9,}")


def _columns(header: str) -> list[tuple[int, str]]:
    """Column start positions and labels, read off the header row.

    The PDF reader lays each page on a character grid, so a column's values sit
    under its own label. Slicing by the header's own positions is what makes
    this layout-driven rather than a guess at field order — and AIS sub-tables
    differ from one another completely: the salary table is quarters, the
    savings-interest table is one row per bank account, the securities table is
    one row per disposal with fourteen columns."""
    groups: list[tuple[int, str]] = []
    start = None
    gap = 0
    for i, ch in enumerate(header):
        if ch != " ":
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            # Labels are wrapped across several words — "ACCOUNT  NUMBER",
            # "SALE  PRICE  PER  UNIT". Three spaces or fewer keeps them
            # together; four starts the next column.
            if gap > 3:
                groups.append((start, header[start:i - gap + 1].strip()))
                start = None
                gap = 0
    if start is not None:
        groups.append((start, header[start:].strip()))
    return [(pos, re.sub(r"\s+", " ", label)) for pos, label in groups if label]


# The securities table in Part B2 is a published CBDT layout with a fixed
# column order, and its numeric columns are right-aligned under left-positioned
# headings, so slicing by heading position splits figures in half. The order
# below is the form's own, and it is only applied when the row yields exactly
# this many figures — a row that yields any other count is reported unmapped
# rather than assigned to the wrong fields.
SECURITY_FIGURES = ["quantity", "sale_price_per_unit", "sale_consideration",
                    "cost_of_acquisition", "fmv_per_unit", "fair_market_value",
                    "indexed_cost_of_acquisition"]
ISIN = re.compile(r"\b(IN[EFD][0-9A-Z]{9})\b")


def _is_securities_table(columns: list[tuple[int, str]]) -> bool:
    labels = " ".join(label for _, label in columns).lower().replace(" ", "")
    return "security" in labels and "quantity" in labels


def _securities_row(raw: str, columns: list[tuple[int, str]]) -> dict:
    """Date, scrip, ISIN and term from the text columns; figures from the tail.

    This is what turns "8,76,540 of securities sold" into a list of disposals
    that can be matched against a broker statement line by line. Category
    totals already reconciled against TIS; what they could never say was which
    trade."""
    def column(predicate):
        for index, (pos, label) in enumerate(columns):
            if predicate(label.lower()):
                nxt = columns[index + 1][0] if index + 1 < len(columns) else len(raw)
                return pos, nxt
        return None, None

    class_at, class_end = column(
        lambda low: low.startswith("security") and "name" not in low)
    asset_at, asset_end = column(lambda low: low.startswith("asset"))
    quantity_at, _ = column(lambda low: low.startswith("quantity"))

    # The scrip name ends where the security-class column begins. Reading to
    # the quantity column instead swept the class, debit type, credit type and
    # term into the name.
    head = raw[:class_at] if class_at else raw[:quantity_at or len(raw)]
    tail = raw[quantity_at:] if quantity_at else ""

    row: dict = {}
    date = DATE.search(head)
    row["date"] = date.group(1) if date else None
    isin = ISIN.search(head)
    row["isin"] = isin.group(1) if isin else None

    name = head[date.end():] if date else head
    name = ISIN.sub(" ", name)
    name = IDENTIFIER.sub(" ", name)
    name = re.sub(r"\(\s*\)", " ", name)
    row["security"] = squash(name).strip(" ()-,") or None

    if class_at is not None:
        row["security_class"] = squash(raw[class_at:class_end]) or None
    if asset_at is not None:
        term = squash(raw[asset_at:asset_end]).lower()
        row["term"] = ("long" if "long" in term else
                       "short" if "short" in term else (term[:20] or None))

    figures = all_money(tail)
    if len(figures) == len(SECURITY_FIGURES):
        row.update(dict(zip(SECURITY_FIGURES, figures)))
    elif figures:
        row["figures_unmapped"] = figures
        row["why_unmapped"] = (
            f"{len(figures)} figures on the row against "
            f"{len(SECURITY_FIGURES)} columns in the form; not assigned")
    return {k: v for k, v in row.items() if v not in (None, "")}


def _slice_row(line: str, columns: list[tuple[int, str]]) -> dict:
    cells: dict[str, str] = {}
    for index, (pos, label) in enumerate(columns):
        end = columns[index + 1][0] if index + 1 < len(columns) else len(line)
        value = line[pos:end].strip() if pos < len(line) else ""
        if value and REDACT_COLUMNS.search(label):
            value = "<redacted>"
        elif value:
            value = IDENTIFIER.sub("<redacted>", value)
            # The reader lays text on a grid by position, so a section heading
            # printed just below a table can share a grid row with its last row
            # and be read as part of it. Two column kinds have exactly one
            # legal shape, so trimming them to it removes the bleed without
            # guessing at anything: a serial number is digits, and a date
            # column holds a date.
            low = label.lower()
            if re.match(r"sr\.?\s*no|^sr\.?$", low):
                head = re.match(r"\d+", value)
                value = head.group(0) if head else value
            elif "date" in low or "reported" in low:
                found = DATE.search(value)
                value = found.group(1) if found else value
        cells[label] = value
    return cells


def parse_ais(pages: list[str]) -> dict:
    entries: list[dict] = []
    part = "B1 — tax deducted or collected at source"
    current: dict | None = None
    columns: list[tuple[int, str]] = []

    for raw in "\n".join(pages).splitlines():
        raw = FURNITURE.sub(lambda m: " " * len(m.group(0)), raw)
        line = squash(raw)
        low = line.lower()
        if not line:
            continue
        for needle, label in AIS_PARTS:
            if low.startswith(needle):
                part = label
                current = None
                columns = []
                break
        if SUMMARY_HEADER.match(low):
            columns = []
            continue
        if SUBTABLE_HEADER.match(low) and not INFO_CODE.search(line):
            # The header is read off the raw line, not the squashed one —
            # squashing collapses the very spacing the columns are defined by.
            found = _columns(raw)
            if len(found) >= 3:
                columns = found
                continue

        code = INFO_CODE.search(line)
        if code:
            values = all_money(line)
            # ... COUNT AMOUNT at the end of a summary row.
            amount = values[-1] if values else None
            count = int(values[-2]) if len(values) >= 2 and values[-2].is_integer() else None
            source = line[code.end():].strip()
            source = re.sub(r"\s*[\d,]+\s*[\d,.]*$", "", source).strip()
            # The reporting entity's TAN is printed next to its name. It is
            # somebody's tax identifier even when it is not the filer's.
            source = re.sub(r"\b[A-Z]{4}\d{5}[A-Z]\b|\b[A-Z]{5}\d{4}[A-Z]\b",
                            "<redacted>", source)
            current = {"part": part, "information_code": code.group(1),
                       "description": squash(line[:code.start()])[:120] or None,
                       "source": source[:120] or None,
                       "count": count, "amount": amount, "rows": []}
            entries.append(current)
            continue

        # Detail rows sit under the summary row they belong to. Where the
        # sub-table header was found they are sliced by its columns, which is
        # what turns "how much" into "which transaction".
        if current is None:
            continue
        if columns and re.match(r"\s*\d{1,4}\s", raw):
            cells = (_securities_row(raw, columns) if _is_securities_table(columns)
                     else _slice_row(raw, columns))
            if any(v for k, v in cells.items() if not k.lower().startswith("sr")):
                current["rows"].append(cells)
            continue
        if columns and current["rows"] and not re.match(r"\s*\d", raw):
            # A wrapped security name or a second line of a narration. It
            # belongs to the row above; dropping it loses the ISIN, which is
            # the only thing that identifies the scrip unambiguously.
            previous_row = current["rows"][-1]
            # A genuine continuation line — a wrapped scrip name — is blank in
            # the serial column. A section heading printed just under the table
            # is not, and appending it put "Saleof securitiesandunitsofmutual
            # fund" inside the last savings row.
            first_end = columns[1][0] if len(columns) > 1 else len(raw)
            if raw[columns[0][0]:first_end].strip():
                continue
            if _is_securities_table(columns):
                extra = _securities_row(raw, columns)
                if extra.get("isin") and not previous_row.get("isin"):
                    previous_row["isin"] = extra["isin"]
                if extra.get("security"):
                    previous_row["security"] = squash(
                        f"{previous_row.get('security', '')} "
                        f"{extra['security']}").strip(" ()-,")
                if extra.get("term") and not previous_row.get("term"):
                    previous_row["term"] = extra["term"]
                continue
            extra = _slice_row(raw, columns)
            for key, value in extra.items():
                if value and value != "<redacted>":
                    previous = previous_row.get(key, "")
                    previous_row[key] = f"{previous} {value}".strip()
            continue
        if DATE.search(line) or low.startswith("q"):
            # Take account numbers out before reading amounts. AIS prints the
            # account a savings-interest figure was reported against, and a
            # long unpunctuated integer is not an amount.
            safe = LONG_DIGITS.sub(" ", line.replace(",", ""))
            values = all_money(safe)
            quarter = re.match(r"\d*\s*(Q[1-4]\([A-Za-z-]+\))", line)
            dates = DATE.findall(line)
            if values or dates:
                current["rows"].append({
                    "quarter": quarter.group(1) if quarter else None,
                    "date": dates[0] if dates else None,
                    "amounts": values[-4:] if values else [],
                })

    by_code: dict[str, float] = defaultdict(float)
    for e in entries:
        if e["amount"] is not None:
            by_code[e["information_code"]] += e["amount"]

    # Where the detail rows carry a consideration, check they add to the
    # category total. AIS rounds each row to whole rupees and computes the
    # total from the unrounded figures, so the two differ by up to half a rupee
    # per row — 108 disposals reconciled to within ₹4. A difference larger than
    # that is rows lost or rows read twice.
    for e in entries:
        priced = [r for r in e["rows"]
                  if isinstance(r, dict) and "sale_consideration" in r]
        if not priced or e["amount"] is None:
            continue
        added = round(sum(r["sale_consideration"] for r in priced), 2)
        tolerance = max(1.0, len(priced) * 0.5)
        e["rows_total"] = added
        e["rows_reconcile"] = (
            f"{len(priced)} row(s) adding to {added:,.0f} against a stated "
            f"{e['amount']:,.0f}"
            + (", which is within per-row rounding"
               if abs(added - e["amount"]) <= tolerance
               else f" — a difference of {abs(added - e['amount']):,.2f}, more "
                    f"than the {tolerance:,.2f} that per-row rounding at half a "
                    f"rupee a row can explain. Rows are missing, or counted "
                    f"twice"))

    # Savings-bank interest is reported one block per bank. This is the only
    # place any document says *which* bank reported what, and it is the first
    # thing to look at when the statements do not add up to the AIS figure.
    #
    # Match the code exactly. SFT-016(SB) and SFT-016(TD) share a prefix and are
    # different money, so a prefix match adds a term deposit into the savings
    # figure. [observed 2026-07-31, one live AY 2026-27 AIS] One reporter filed
    # both codes; the headline then named a savings total that included the
    # deposit, and overstated the bank count, while the correct savings total
    # was already being printed by totals_by_information_code two lines earlier.
    # It also reached reconcile_interest.py, which compares this figure against
    # the bank statements and reported a discrepancy against an account that was
    # never missing. Figures are in the fixture, not here.
    def _by_reporter(code):
        return [{"reported_by": e["source"], "amount": e["amount"]}
                for e in entries
                if e["information_code"] == code and e["amount"] is not None]

    savings = _by_reporter("SFT-016(SB)")
    deposits = _by_reporter("SFT-016(TD)")
    result = {"entries": entries, "totals_by_information_code": dict(by_code)}
    if savings:
        named, unnamed = reporter_counts(savings)
        result["savings_bank_interest_by_reporter"] = {
            # One reporter may file more than one block — two accounts at one
            # bank produce two. `banks` counts distinct named reporters so it
            # means what it says; `blocks` keeps the raw count visible.
            "banks": named,
            "blocks": len(savings),
            "blocks_with_unread_reporter": unnamed,
            "total": round(sum(s["amount"] for s in savings), 2),
            "reporters": savings,
        }
    if deposits:
        named, unnamed = reporter_counts(deposits)
        result["term_deposit_interest_by_reporter"] = {
            "reporters_count": named,
            "blocks": len(deposits),
            "blocks_with_unread_reporter": unnamed,
            "total": round(sum(d["amount"] for d in deposits), 2),
            "reporters": deposits,
            # [documented] s.80TTA(1) covers interest on deposits in a *savings
            # account* only. [documented] s.80TTB covers a resident senior
            # citizen (60+) for interest on deposits generally, term deposits
            # included, up to 50,000 — and a filer claiming 80TTB cannot also
            # claim 80TTA. Both are old-regime only; s.115BAC(2) allows neither.
            "note": "Interest on deposits, not a savings account, so s.80TTA "
                    "does not reach it. Under the old regime a resident senior "
                    "citizen may still deduct this under s.80TTB, up to 50,000 "
                    "across deposit interest generally. Under the new regime "
                    "neither section is available and it is taxable in full.",
        }
    return result


def reporter_counts(rows: list[dict]) -> tuple[int, int]:
    """Distinct named reporters, and blocks whose reporter was not read.

    Extraction can lose the source text of a block. Folding those into a
    distinct count collapses every unknown reporter into one bank and
    understates how many statements are still missing, so they are counted
    separately rather than guessed at. Module level so this is testable
    directly: no readable fixture produces a block with no source."""
    named = {r["reported_by"] for r in rows if r.get("reported_by")}
    return len(named), sum(1 for r in rows if not r.get("reported_by"))


# ------------------------------------------------------- Form 26AS / Form 168

FORM26AS_PARTS = {
    "part i": "I — TDS",
    "part ii": "II — TDS where Form 15G/15H was furnished",
    "part iii": "III — TDS on winnings, benefits and VDA",
    "part iv": "IV — TDS u/s 194IA/IB/M/S as seller",
    "part v": "V — TDS u/s 194S as VDA seller",
    "part vi": "VI — TCS",
    "part vii": "VII — refunds paid",
    "part viii": "VIII — TDS u/s 194IA/IB/M/S as buyer (information only, not a credit)",
    "part ix": "IX — TDS u/s 194S as VDA buyer (information only, not a credit)",
    "part x": "X — TDS/TCS defaults",
    "part xi": "XI — TDS/TCS credit allowed by the Assessing Officer u/s 398",
}
NON_FINAL = {"U": "unmatched", "M": "matched, not final", "O": "overbooked",
             "P": "provisional", "Z": "mismatch"}


def parse_26as(pages: list[str]) -> dict:
    deductors: list[dict] = []
    part = "I — TDS"
    summary: dict = {}
    text = "\n".join(pages)

    head = squash(text[:3000])
    tds = re.search(r"TDS\s*₹?\s*([\d,]+\.\d{2})", head)
    if tds:
        summary["total_tds"] = money(tds.group(1))
    form = "Form 168" if "form168" in head.lower() else "Form 26AS"
    year = re.search(r"(Tax Year|Assessment Year)\s*(20\d{2}-\d{2})", head)

    for raw in text.splitlines():
        line = squash(raw)
        low = line.lower()
        if not line:
            continue
        matched_part = False
        for needle, label in FORM26AS_PARTS.items():
            if re.match(rf"part\s+{needle.split()[1]}\b", low):
                part, matched_part = label, True
                break
        if matched_part or low.startswith("s.no"):
            continue
        tan = TAN.search(line)
        if tan:
            values = all_money(line)
            deductors.append({
                "part": part,
                "deductor": squash(line[:tan.start()]).lstrip("0123456789 ")[:90] or None,
                "tan": tan.group(0),
                "amount_paid": values[-3] if len(values) >= 3 else None,
                "tax_deducted": values[-2] if len(values) >= 2 else None,
                "tds_deposited": values[-1] if values else None,
            })

    creditable = [d for d in deductors if "information only" not in d["part"]]
    return {
        "form": form,
        "year": year.group(2) if year else None,
        "summary": summary,
        "deductors": deductors,
        "total_tds_deposited": round(
            sum(d["tds_deposited"] or 0 for d in creditable), 2),
        "note": ("Parts VIII and IX are informational — TDS you deducted as a "
                 "buyer is not your credit. They are excluded from the total."),
    }


# --------------------------------------------------------------------- Form 16

FORM16_FIELDS = [
    (r"opting out of taxation u/s 115BAC", "opted_out_of_new_regime", "yesno"),
    (r"salary as per provisions contained in section 17\(1\)", "salary_17_1", "money"),
    (r"value of perquisites under section 17\(2\)", "perquisites_17_2", "money"),
    (r"profits in lieu of salary under section 17\(3\)", "profits_in_lieu_17_3", "money"),
    (r"reported total amount of salary received from other employer", "salary_other_employers", "money"),
    (r"travel concession or assistance under section 10\(5\)", "exempt_10_5", "money"),
    (r"house rent allowance under section 10\(13A\)", "exempt_10_13a", "money"),
    (r"standard deduction under section 16\(ia\)", "standard_deduction_16_ia", "money"),
    (r"entertainment allowance under section 16\(ii\)", "deduction_16_ii", "money"),
    (r"tax on employment under section 16\(iii\)", "professional_tax_16_iii", "money"),
    (r"income chargeable under the head .salary", "income_from_salary", "money"),
    (r"total amount of other income reported", "other_income_reported", "money"),
    (r"gross total income", "gross_total_income", "money"),
    (r"total deduction under chapter vi-a", "chapter_via_total", "money"),
    (r"total taxable income", "total_income", "money"),
    (r"tax on total income", "tax_on_total_income", "money"),
    (r"rebate under section 87a", "rebate_87a", "money"),
    (r"health and education cess", "cess", "money"),
    (r"net tax payable", "net_tax_payable", "money"),
]


def parse_form16(pages: list[str]) -> dict:
    text = "\n".join(pages)
    out: dict = {}
    for raw in text.splitlines():
        line = squash(raw)
        low = line.lower()
        for pattern, key, kind in FORM16_FIELDS:
            if re.search(pattern, low):
                if kind == "yesno":
                    out[key] = low.rstrip().endswith("yes")
                else:
                    tail = re.search(r"(-?[\d,]+\.\d{2})\s*$", line)
                    if tail and key not in out:
                        out[key] = float(tail.group(1).replace(",", ""))
                break

    quarters = []
    for raw in text.splitlines():
        line = squash(raw)
        m = re.match(r"Q([1-4])\s+([A-Z0-9]{8})\s+(.*)$", line)
        if m:
            values = all_money(m.group(3))
            if len(values) >= 3:
                quarters.append({"quarter": f"Q{m.group(1)}",
                                 "receipt_number": m.group(2),
                                 "amount_paid": values[0],
                                 "tax_deducted": values[1],
                                 "tax_deposited": values[2]})
    if quarters:
        out["quarterly"] = quarters
        out["tds_total"] = round(sum(q["tax_deposited"] for q in quarters), 2)

    tan = TAN.search(text)
    if tan:
        out["deductor_tan"] = tan.group(0)
    period = DATE.findall(text)
    if len(period) >= 2:
        out["certificate_last_updated"] = period[0]
    m = re.search(r"From\s+To\s*\n?", text)
    spans = re.findall(r"(\d{2}-[A-Za-z]{3}-\d{4})\s+(\d{2}-[A-Za-z]{3}-\d{4})", text)
    if spans:
        out["employment_from"], out["employment_to"] = spans[-1]

    if out.get("opted_out_of_new_regime") is False:
        out["regime"] = "new (s.115BAC(1A) default, not opted out)"
    elif out.get("opted_out_of_new_regime"):
        out["regime"] = "old (opted out via Form 10-IEA)"
    return out


# ------------------------------------------------------------ reconciliation

def reconcile(docs: list[dict]) -> dict:
    checks: list[str] = []
    flags: list[str] = []
    by_kind = {d["document"]: d for d in docs}

    tis, ais = by_kind.get("TIS"), by_kind.get("AIS")
    f16 = by_kind.get("FORM16B") or by_kind.get("FORM16A")
    as26 = by_kind.get("26AS")

    if tis:
        cats = tis["data"]["categories"]
        if cats:
            checks.append(
                "TIS categories, at the accepted-by-taxpayer value: "
                + "; ".join(f"{k} {v['accepted_by_taxpayer']:,.0f}"
                            for k, v in sorted(cats.items())))
        for label, values in cats.items():
            if values["processed_by_system"] != values["accepted_by_taxpayer"]:
                flags.append(
                    f"TIS {label}: processed by system "
                    f"{values['processed_by_system']:,.0f} but accepted "
                    f"{values['accepted_by_taxpayer']:,.0f}. Feedback has been "
                    "filed against this category — use the accepted figure and "
                    "keep the reason.")
        if "Sale of securities and mutual-fund units" in cats:
            checks.append(
                "TIS reports a sale of securities, so a broker Tax P&L is "
                "mandatory. TIS gives consideration, never gain — it cannot tell "
                "you the tax. Run parse_capital_gains.py on the broker file.")

    if f16 and as26:
        f16_tds = f16["data"].get("tds_total")
        as_tds = as26["data"].get("total_tds_deposited")
        if f16_tds and as_tds:
            if abs(f16_tds - as_tds) <= 1:
                checks.append(f"Form 16 TDS ({f16_tds:,.2f}) ties to "
                              f"{as26['data']['form']} ({as_tds:,.2f}).")
            else:
                flags.append(
                    f"Form 16 shows TDS of {f16_tds:,.2f} but "
                    f"{as26['data']['form']} shows {as_tds:,.2f}. Claim the "
                    f"{as26['data']['form']} figure — that is the credit the "
                    "department will allow — and ask the employer to correct "
                    "the other before filing.")

    if f16:
        d = f16["data"]
        parts = [d.get("salary_17_1"), d.get("perquisites_17_2"),
                 d.get("profits_in_lieu_17_3")]
        if all(p is not None for p in parts):
            checks.append(
                f"Form 16: 17(1) {parts[0]:,.2f} + 17(2) {parts[1]:,.2f} + "
                f"17(3) {parts[2]:,.2f} = {sum(parts):,.2f} gross salary.")
        if d.get("regime"):
            checks.append(f"Form 16 was computed on the {d['regime']} regime. "
                          "You may still choose the other one when filing, "
                          "subject to Form 10-IEA and the due date.")
        if d.get("other_income_reported"):
            flags.append(
                f"Form 16 already carries {d['other_income_reported']:,.2f} of "
                "other income declared to the employer. Do not add it twice.")

    if ais:
        codes = ais["data"]["totals_by_information_code"]
        if any(k == "TDS-194" for k in codes) and any(k == "SFT-015" for k in codes):
            checks.append(
                f"AIS lists dividend twice by design: SFT-015 {codes['SFT-015']:,.0f} "
                f"from the registrar and TDS-194 {codes['TDS-194']:,.0f} from the "
                "company's own TDS return, covering the same money. TIS "
                "deduplicates them. Report the TIS figure, not the sum.")
        if codes:
            checks.append("AIS by information code: "
                          + "; ".join(f"{k} {v:,.0f}" for k, v in sorted(codes.items())))
        if any(c.startswith("TDS-192A") for c in codes):
            flags.append(
                "TDS u/s 192A is present, which means a PF withdrawal. Exempt "
                "only with five years of continuous service — service length, "
                "not time to withdrawal. See references/rates-ay2026-27.md.")

    if ais and tis:
        # TIS is a derived roll-up of the AIS detail. Proving the detail sums to
        # the category is the strongest check available on these two documents,
        # and a category that does not tie is where a missed source hides.
        codes = ais["data"]["totals_by_information_code"]
        cats = tis["data"]["categories"]

        def total(*prefixes):
            return round(sum(v for k, v in codes.items()
                             if any(k.startswith(p) for p in prefixes)), 2)

        mapping = [
            # TDS-194 is the company's own TDS return on the same dividend the
            # registrar reports under SFT-015. AIS lists both; TIS deduplicates
            # them. Adding TDS-194 here double-counts. s.194K dividend on mutual
            # fund units is a separate source and does add.
            ("Dividend", ("SFT-015", "TDS-194K")),
            ("Interest — savings bank", ("SFT-016(SB)",)),
            ("Interest — deposits", ("SFT-016(TD)", "TDS-194A")),
            ("PF withdrawal", ("TDS-192A",)),
            ("Salary", ("TDS-192",)),
            ("Sale of securities and mutual-fund units",
             ("SFT-17-", "SFT-18-")),
            ("Purchase of securities and mutual-fund units",
             ("SFT-17(Pur", "SFT-18(Pur", "SFT-008", "SFT-010")),
        ]
        for label, prefixes in mapping:
            if label not in cats:
                continue
            detail = total(*prefixes)
            stated = cats[label]["accepted_by_taxpayer"]
            if detail == 0:
                continue
            if abs(detail - stated) <= 1:
                checks.append(
                    f"AIS ties to TIS on {label}: "
                    f"{' + '.join(sorted(k for k in codes if any(k.startswith(p) for p in prefixes)))}"
                    f" = {detail:,.0f}.")
            else:
                flags.append(
                    f"{label}: the AIS detail sums to {detail:,.0f} but TIS says "
                    f"{stated:,.0f}, a difference of {stated - detail:+,.0f}. "
                    "Find the missing or duplicated source before filing — TIS "
                    "deduplicates and AIS does not, so a gap usually means one "
                    "source was counted twice in AIS or dropped from TIS.")

        checks.append(
            "AIS and TIS are two views of the same feed: AIS is the "
            "transaction detail, TIS the derived value the portal prefills "
            "from. Where they differ, the return follows TIS and the difference "
            "is worth an explanation in your working papers.")

    flags.append(
        "AIS silence is not evidence. A filer with a full year of equity "
        "disposals had nothing reported under any SFT category. Ask for bank "
        "and broker statements whatever these documents show.")
    return {"checks": checks, "flags": flags}


PARSERS = {"TIS": parse_tis, "AIS": parse_ais, "26AS": parse_26as,
           "FORM16A": parse_form16, "FORM16B": parse_form16}


def summarise(result: dict) -> str:
    """Print the document identity and the figures a filer reads first."""
    money = lambda value: f"₹{value:,.2f}"
    tis_qualifiers = {
        "Sale of securities and mutual-fund units":
            "consideration, not gain; accepted-by-taxpayer value",
        "Purchase of securities and mutual-fund units":
            "purchase value, not income; accepted-by-taxpayer value",
        "Sale of immovable property":
            "consideration, not capital gain; accepted-by-taxpayer value",
        "Purchase of immovable property":
            "purchase value, not income; accepted-by-taxpayer value",
        "PF withdrawal":
            "gross withdrawal, taxability not determined; accepted-by-taxpayer value",
        "Business receipts":
            "gross receipts, not profit; accepted-by-taxpayer value",
        "Rent received":
            "gross receipt, before deductions; accepted-by-taxpayer value",
        "GST turnover":
            "turnover, not profit; accepted-by-taxpayer value",
        "Off-market debit":
            "transaction value, tax treatment not determined; accepted-by-taxpayer value",
        "Off-market credit":
            "transaction value, tax treatment not determined; accepted-by-taxpayer value",
        "Winnings":
            "gross receipts, tax treatment not determined; accepted-by-taxpayer value",
        "Life insurance receipts":
            "gross receipts, taxability not determined; accepted-by-taxpayer value",
    }

    def ais_label(code: str) -> str:
        if code.startswith("TDS-"):
            return f"{code} reported gross amount (not TDS deducted)"
        if code.startswith(("SFT-17-LES", "SFT-18-LES")):
            return f"{code} sale consideration (not gain)"
        if "(Pur" in code or code in {"SFT-008", "SFT-010"}:
            return f"{code} purchase value (not income)"
        return f"{code} reported amount"

    lines = []
    for entry in result["documents"]:
        period = f"FY {entry['period']}" if entry.get("period") \
            else "period not identified"
        lines.append(
            f"{entry['file']}: {entry['document']} — {period} — "
            f"{entry['pages']} page(s)")
        data = entry["data"]
        totals = data.get("totals_by_information_code")
        if totals:
            for label, amount in sorted(totals.items()):
                lines.append(f"  {ais_label(label)}: {money(amount)}")
        categories = data.get("categories")
        if categories:
            for label, values in categories.items():
                amount = next((values.get(key) for key in (
                    "accepted_by_taxpayer", "processed_value", "derived_value",
                    "reported_value") if values.get(key) is not None), None)
                if amount is not None:
                    qualifier = tis_qualifiers.get(
                        label, "accepted-by-taxpayer value")
                    lines.append(f"  {label} — {qualifier}: {money(amount)}")
        def unread_suffix(block):
            """Name blocks whose reporter was not read rather than folding them
            into the bank count, which would understate missing statements."""
            unread = block.get("blocks_with_unread_reporter") or 0
            return (f", plus {unread} block(s) whose reporter could not be read"
                    if unread else "")

        savings = data.get("savings_bank_interest_by_reporter")
        if savings:
            lines.append(
                f"  savings-bank interest: {money(savings['total'])} "
                f"from {savings['banks']} bank(s){unread_suffix(savings)}")
        deposits = data.get("term_deposit_interest_by_reporter")
        if deposits:
            # Named separately on purpose: s.80TTA reaches the savings figure
            # above and not this one. s.80TTB may reach this one, but only for a
            # resident senior citizen and only under the old regime, which is
            # not something this script knows — so it points rather than decides.
            lines.append(
                f"  term-deposit interest: {money(deposits['total'])} "
                f"from {deposits['reporters_count']} reporter(s)"
                f"{unread_suffix(deposits)} — not savings, outside s.80TTA; "
                f"see s.80TTB if the filer is a resident senior citizen on the "
                f"old regime")
        if data.get("total_tds_deposited") is not None:
            lines.append(f"  TDS deposited: {money(data['total_tds_deposited'])}")
        for label, key in (
            ("gross total income", "gross_total_income"),
            ("total income", "total_income"),
            ("net tax payable", "net_tax_payable"),
            ("TDS deposited", "tds_total"),
        ):
            if data.get(key) is not None:
                lines.append(f"  {label}: {money(data[key])}")
    required_context = [
        check for check in result["checks"]
        if "broker Tax P&L is mandatory" in check
        or "AIS lists dividend twice by design" in check
    ]
    if required_context:
        lines.extend(["", "Required context", *required_context])
    if result["flags"]:
        lines.extend(["", "Flags", *result["flags"]])
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", metavar="PATH", help="write the full result to a file")
    ap.add_argument("--text", action="store_true",
                    help="print the extracted text instead of parsing it")
    ap.add_argument("--summary", action="store_true",
                    help="print the key figures and every flag as plain lines")
    ap.add_argument("--password", help="for encrypted AIS, TIS, Form 16 or a "
                                       "s.143(1) intimation: lowercase PAN "
                                       "followed by ddmmyyyy")
    ap.add_argument("--password-stdin", action="store_true",
                    help="read the password from standard input instead, so it "
                         "never appears in argv or in shell history")
    a = ap.parse_args(argv)

    if a.summary and a.text:
        print(json.dumps({
            "refused": "--summary and --text are two different stdout modes. "
                       "Use --summary for parsed figures or --text for the "
                       "extracted document text."
        }, indent=2), file=sys.stderr)
        return 2

    try:
        password = resolve_password(a.password, a.password_stdin)
    except CryptError as e:
        print(json.dumps({"refused": str(e)}, indent=2), file=sys.stderr)
        return 2

    docs = []
    for path in a.files:
        try:
            pages = extract_pages(path, password)
        except PdfError as e:
            print(json.dumps({"refused": str(e), "file": safe_name(path)},
                             indent=2), file=sys.stderr)
            return 2
        text = "\n".join(pages)
        if a.text:
            print(f"----- {safe_name(path)} -----")
            print(text)
            continue
        kind = detect(text)
        entry = {"file": safe_name(path), "document": kind,
                 "pages": len(pages), **identity(text)}
        if kind in PARSERS:
            entry["data"] = PARSERS[kind](pages)
        else:
            entry["data"] = {}
            entry["note"] = ("Document type not recognised. Run with --text to "
                             "see what it holds, and open an issue with the "
                             "headings only — no figures, no identifiers.")
        docs.append(entry)

    if a.text:
        return 0

    result = {"documents": docs, **reconcile(docs)}
    result["disclaimer"] = (
        "Read from the documents as given. It reconciles them to each other; it "
        "does not verify any of them. Nothing here reproduces a PAN, an Aadhaar "
        "number or an account number, but the source files do — keep them out of "
        "public issues.")
    if a.summary:
        print(summarise(result))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
