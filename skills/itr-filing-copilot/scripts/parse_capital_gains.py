#!/usr/bin/env python3
"""
Read a broker or registrar capital-gains statement and emit structured,
classified data for Schedule CG.

Standard library only. Reads nothing but the files you name. No network.

    python3 parse_capital_gains.py tax_pnl.xlsx
    python3 parse_capital_gains.py zerodha.xlsx groww_mf.xlsx --json out.json
    python3 parse_capital_gains.py --inspect unknown_broker.xlsx

Why this exists
---------------
The errors that cost Indian filers money are not slab errors. They are
transcription and classification errors: equity mutual-fund LTCG entered as
"other than 112A" so the 1,25,000 exemption is forfeited, equity STCG taxed at
slab instead of 20% u/s 111A, the 1,25,000 exemption claimed once per broker
instead of once per PAN, intraday profit reported as capital gains when it is
speculative business income that forces ITR-3. A model reading a 400-row
spreadsheet makes those mistakes. A parser does not.

What it will not do
-------------------
It will not guess whether a mutual fund is equity-oriented. Section headings
do not say, and the difference decides between 12.5% with a 1,25,000 exemption
and slab rates. Unclassifiable rows come back under `needs_confirmation` with
the question that resolves them, and the totals exclude them. Cross-check
against AIS: SFT-18-EMF with non-zero STT is equity-oriented, SFT-18-OTU with
zero STT is not.

Layouts
-------
No broker publishes a stable layout, and several change theirs between
financial years, so nothing here is positional. Sections are found by their
heading text, columns by matching header labels, and anything unrecognised is
reported rather than dropped. `--inspect` prints what the file looks like so
an unknown layout can be described in an issue.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from redact import safe_name  # noqa: E402
from read_tabular import (SpreadsheetError, cell_text, load_sheets,  # noqa: E402
                          non_empty, row_text)

# --------------------------------------------------------------- classification

# ITR buckets. The key is what the rest of the toolchain uses; `schedule` is
# where it lands on the form.
BUCKETS = {
    "111A":       {"schedule": "CG A2 / A3", "label": "STCG on equity or equity MF, STT paid — 20%"},
    "112A":       {"schedule": "CG B3 (ITR-2) / B4 (ITR-3), plus Schedule 112A",
                   "label": "LTCG on equity or equity MF, STT paid — 12.5% above 1,25,000"},
    "stcg_slab":  {"schedule": "CG A5 (ITR-2) / A6 (ITR-3)", "label": "STCG on other assets — slab rates"},
    "112":        {"schedule": "CG B5 (ITR-2) / B6 (ITR-3)", "label": "LTCG on other assets — 12.5%"},
    "speculative": {"schedule": "Schedule BP — speculative business", "label": "Intraday equity — speculative business income, forces ITR-3"},
    "fno":        {"schedule": "Schedule BP — non-speculative business", "label": "F&O — non-speculative business income, forces ITR-3"},
    "dividend":   {"schedule": "Schedule OS", "label": "Dividend — slab rates, surcharge capped at 15%"},
}

# Section headings seen in the wild, matched on the lowercased heading.
# Each rule is (must contain all of these, must contain none of these, bucket).
#
# Order is load-bearing and the exclusions are not decoration. "equity" is a
# substring of "non-equity", so a debt-fund section reads as equity unless it is
# excluded, and that single mistake hands the filer a 1,25,000 exemption they are
# not entitled to and takes their gains out of slab rates. Every exclusion below
# is a case that misclassified during testing.
_EQ_NOT = ("non equity", "non-equity", "nonequity", "unlisted", "foreign",
           "buyback", "buy back", "debt", "us stock", "overseas")

SECTION_RULES = [
    # Business income first: it decides the form, and its headings often carry
    # the word equity.
    (("buyback",), (), "buyback"),
    (("buy back",), (), "buyback"),
    (("currency",), (), "fno"),
    (("commodity",), (), "fno"),
    (("f&o",), (), "fno"),
    (("fno",), (), "fno"),
    (("futures",), (), "fno"),
    (("options",), (), "fno"),
    (("intraday",), ("currency", "commodity"), "speculative"),
    (("speculative",), (), "speculative"),
    (("day trading",), (), "speculative"),

    # Explicitly non-equity, before anything containing "equity".
    (("non equity",), (), "nonequity_unknown"),
    (("non-equity",), (), "nonequity_unknown"),
    (("nonequity",), (), "nonequity_unknown"),
    (("debt",), (), "nonequity_unknown"),
    (("unlisted",), (), "unlisted_unknown"),
    (("foreign",), (), "foreign_unknown"),
    (("us stock",), (), "foreign_unknown"),
    (("overseas",), (), "foreign_unknown"),
    (("land",), (), "landbuilding_unknown"),
    (("building",), (), "landbuilding_unknown"),
    (("property",), (), "landbuilding_unknown"),
    (("gold bond",), (), "nonequity_unknown"),
    (("sovereign gold",), (), "nonequity_unknown"),

    # Equity, now safe to match loosely.
    (("equity", "short term"), _EQ_NOT, "111A"),
    (("equity", "short-term"), _EQ_NOT, "111A"),
    (("equity", "stcg"), _EQ_NOT, "111A"),
    (("equity", "long term"), _EQ_NOT, "112A"),
    (("equity", "long-term"), _EQ_NOT, "112A"),
    (("equity", "ltcg"), _EQ_NOT, "112A"),
    (("listed", "short term"), _EQ_NOT, "111A"),
    (("listed", "long term"), _EQ_NOT, "112A"),
    (("111a",), (), "111A"),
    (("112a",), (), "112A"),

    (("dividend",), (), "dividend"),
    (("mutual fund",), ("debt", "non equity", "non-equity"), "mf_unknown"),
    (("sip",), (), "mf_unknown"),

    # Last resort: a bare short/long term heading names no asset class, and the
    # asset class is what decides the rate.
    (("short term",), (), "stcg_unknown"),
    (("short-term",), (), "stcg_unknown"),
    (("stcg",), (), "stcg_unknown"),
    (("long term",), (), "ltcg_unknown"),
    (("long-term",), (), "ltcg_unknown"),
    (("ltcg",), (), "ltcg_unknown"),
]

# Header labels -> canonical field. Matched as substrings on the lowercased
# cell, longest pattern first so "sell value" beats "value".
HEADER_RULES = [
    ("scrip name", "name"), ("scheme name", "name"), ("stock name", "name"),
    ("security name", "name"), ("particulars", "name"), ("instrument", "name"),
    ("description", "name"), ("symbol", "name"), ("scrip", "name"),
    ("security", "name"), ("name", "name"),
    ("isin", "isin"),
    ("entry date", "buy_date"), ("purchase date", "buy_date"), ("buy date", "buy_date"),
    ("date of purchase", "buy_date"), ("acquisition date", "buy_date"),
    ("date of acquisition", "buy_date"),
    ("exit date", "sell_date"), ("redeem date", "sell_date"), ("sell date", "sell_date"),
    ("sale date", "sell_date"), ("date of sale", "sell_date"), ("date of transfer", "sell_date"),
    ("matched quantity", "quantity"), ("quantity", "quantity"), ("units", "quantity"), ("qty", "quantity"),
    ("buy value", "buy_value"), ("purchase value", "buy_value"), ("cost of acquisition", "buy_value"),
    ("buy amount", "buy_value"), ("purchase amount", "buy_value"),
    ("sell value", "sell_value"), ("sale value", "sell_value"), ("sell amount", "sell_value"),
    ("sales consideration", "sell_value"), ("redemption amount", "sell_value"),
    ("fair market value", "fmv"), ("unit fmv", "fmv_per_unit"),
    ("taxable profit", "gain"), ("realised p&l", "gain"), ("realized p&l", "gain"),
    ("short term-capital gain", "gain"), ("long term-capital gain", "gain"),
    ("profit/loss", "gain"), ("profit", "gain"), ("p&l", "gain"), ("gain", "gain"),
    ("period of holding", "holding"), ("holding days", "holding"), ("holding period", "holding"),
    ("turnover", "turnover"),
    ("transfer expense", "expenses"), ("total charges", "expenses"),
    ("expenditure", "expenses"), ("expenses", "expenses"), ("charges", "expenses"),
    ("brokerage", "expenses"),
    ("dividend per share", "dps"), ("net dividend", "amount"),
    ("dividend amount", "amount"), ("ex-date", "sell_date"), ("ex date", "sell_date"),
]
HEADER_RULES.sort(key=lambda kv: -len(kv[0]))

# Sheets that are not realised gains. "Open Positions" carries UNREALISED
# profit on holdings still open at year end, which is not income at all; the
# rest are charges and balances. Reading them produces figures that look like
# gains and are not.
SKIP_SHEETS = ("open position", "ledger balance", "other debits and credits",
               "charges", "disclaimer", "notes", "instructions")

MONEY_FIELDS = ("buy_value", "sell_value", "gain", "turnover", "fmv", "amount",
                "expenses")

# A column carrying any of these is never the figure that goes on the return.
# Zerodha ships an "Unrealized P&L" column next to the realised one, and first
# match wins, so without this the whole bucket takes the notional number.
DECOY_WORDS = ("unrealis", "unrealiz", "notional", "mtm", "mark to market",
               "opening", "closing", "carried forward", "brought forward",
               "previous year", "estimated", "projected")
# "sum" as a substring eats SUMICHEM (Sumitomo Chemical, NSE-listed) and any
# scrip beginning Summit; a bare "total" test misses "Subtotal" and "Overall
# Total". Both mistakes are silent and both change the totals, so this is a
# whole-label match on word boundaries.
TOTAL_LABEL = re.compile(
    r"^(?:sub|grand|net|overall|running|closing)?[\s\-]*(?:totals?|summary)"
    r"(?:\s+(?:for|of)\b.*)?\s*[:\-]?\s*$", re.I)

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y",
                "%Y/%m/%d", "%m/%d/%Y", "%d.%m.%Y")


def to_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("₹", "").replace("Rs.", "")
    s = s.replace("(", "-").replace(")", "")
    if s in ("", "-", "--", "NA", "N/A", "nil", "Nil"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_iso_date(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    s = str(value).strip()
    if not s:
        return None
    s = s.split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2} ", s) else s
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def is_total_label(text: str) -> bool:
    """True only where the whole label is a total or summary label.

    A prefix test would eat SUMICHEM and TOTAL ENERGIES, both real listed
    scrips; a bare equality test would miss Subtotal and Overall Total. Both
    mistakes change the figures and neither says anything."""
    return bool(TOTAL_LABEL.match(cell_text(text).strip().strip("*#. ")))


def match_section(text: str) -> str | None:
    low = text.lower()
    for needles, excludes, bucket in SECTION_RULES:
        if all(n in low for n in needles) and not any(x in low for x in excludes):
            return bucket
    return None


def map_header(row: list) -> dict[str, list[int]] | None:
    """Return {field: [candidate column indices]} if this row is a header row.

    Every candidate is kept rather than the first match, because a decoy column
    ahead of the real one silently poisons the whole bucket: a text column
    headed "Nature of Gain" ahead of "Realised P&L" produced a bucket reading
    zero, with one row in it and no complaint."""
    mapping: dict[str, list[int]] = {}
    for idx, cell in enumerate(row):
        text = cell_text(cell).lower()
        if not text or len(text) > 60:
            continue
        if any(d in text for d in DECOY_WORDS):
            continue
        for needle, field in HEADER_RULES:
            if needle in text:
                mapping.setdefault(field, []).append((len(needle), idx))
                break
    # A header row has to identify the instrument and at least one number.
    if "name" not in mapping or not (set(mapping) &
                                     {"gain", "sell_value", "amount", "quantity"}):
        return None
    # Most specific header first. Zerodha prints "Profit" before "Taxable
    # Profit"; the second is the grandfathered figure that belongs on the return,
    # so leftmost-wins would quietly use the pre-grandfathering number.
    return {field: [idx for _, idx in sorted(hits, key=lambda h: (-h[0], h[1]))]
            for field, hits in mapping.items()}


# ------------------------------------------------------------------- the parser

class Statement:
    def __init__(self, path: str):
        self.path = path
        self.file = safe_name(path)
        self.records: list[dict] = []
        self.warnings: list[str] = []
        self.unparsed_sections: list[str] = []
        self.skipped_sheets: list[str] = []
        self.stated: dict[str, float] = {}
        self.dropped_views: list[str] = []
        self.has_identifiers = False
        self.source = "unknown"

    def add(self, bucket: str, mapping: dict[str, list[int]], row: list,
            section: str, sheet: str = ""):
        rec: dict = {"file": self.file, "sheet": sheet, "section": section,
                     "bucket": bucket}
        for field, candidates in mapping.items():
            numeric = field in MONEY_FIELDS or field in ("quantity", "dps",
                                                         "holding", "fmv_per_unit")
            value, unreadable = None, None
            for idx in candidates:
                if idx >= len(row):
                    continue
                raw = row[idx]
                if numeric:
                    value = to_number(raw)
                elif field in ("buy_date", "sell_date"):
                    value = to_iso_date(raw)
                    if value is None and cell_text(raw):
                        unreadable = cell_text(raw)
                else:
                    value = cell_text(raw) or None
                if value is not None:
                    break
            rec[field] = value
            if value is None and unreadable:
                rec.setdefault("flags", []).append(f"unreadable date {unreadable!r}")
        if rec.get("gain") is None and rec.get("sell_value") is not None \
                and rec.get("buy_value") is not None:
            expenses = rec.get("expenses") or 0
            rec["gain"] = round(rec["sell_value"] - rec["buy_value"] - expenses, 2)
            rec.setdefault("flags", []).append(
                "gain derived as sell minus buy"
                + (" minus stated expenses" if expenses else
                   "; the statement stated no expenses, so any transfer cost is "
                   "not deducted") + "; the statement did not state a gain")
        if all(rec.get(f) is None for f in ("gain", "sell_value", "buy_value", "amount")):
            rec.setdefault("flags", []).append(
                "every money column on this row read as empty — the column may "
                "hold text, or a formula the file never calculated")
        if rec.get("amount") is None and rec.get("dps") and rec.get("quantity"):
            rec["amount"] = round(rec["dps"] * rec["quantity"], 2)
        if rec.get("name") is None:
            return
        self.records.append(rec)


def broker_stated_totals(sheets: dict[str, list[list]]) -> dict[str, float]:
    """The figures the statement states about itself.

    Most brokers print a realised-profit breakdown, and it is an independent
    check on the rows: if they disagree, one of the two is wrong and the filer
    needs to know before the number reaches a return."""
    out: dict[str, float] = {}
    for rows in sheets.values():
        for row in rows:
            cells = non_empty(row)
            if len(cells) != 2:
                continue
            label, value = cell_text(cells[0]), to_number(cells[1])
            if value is None or "profit" not in label.lower():
                continue
            if is_total_label(label) or "turnover" in label.lower():
                continue
            bucket = match_section(label)
            if bucket:
                out[bucket] = out.get(bucket, 0.0) + value
    return out


def detect_source(sheets: dict[str, list[list]]) -> str:
    names = " ".join(sheets).lower()
    head = " ".join(row_text(r).lower() for rows in sheets.values() for r in rows[:6])
    for needle, label in (("zerodha", "zerodha"), ("kite", "zerodha"), ("groww", "groww"),
                          ("upstox", "upstox"), ("angel", "angel-one"), ("indmoney", "indmoney"),
                          ("dhan", "dhan"), ("icici", "icici-direct"), ("kotak", "kotak"),
                          ("hdfc sec", "hdfc-securities"), ("paytm", "paytm-money"),
                          ("5paisa", "5paisa"), ("cams", "cams"), ("kfintech", "kfintech")):
        if needle in names or needle in head:
            return label
    if "tradewise" in names:
        return "zerodha"
    return "unknown"


def is_stated_figure(row: list) -> bool:
    """A label and a number on their own — a summary line, not a data row.

    Realised-profit breakdowns, turnover breakdowns and charge tables are all
    written this way. They are read by broker_stated_totals() as a cross-check,
    and reporting them as unparsed rows buries the warnings that matter."""
    cells = non_empty(row)
    return (len(cells) == 2 and to_number(cells[0]) is None
            and to_number(cells[1]) is not None)


def looks_like_heading(row: list) -> bool:
    """A heading names a section and carries no figures.

    Testing for exactly one populated cell is not enough: a heading with a note
    beside it ("Equity - Long Term", "(STT paid)") reads as data, the section
    change is lost, and every row beneath it is taxed under the previous
    heading's rate."""
    cells = non_empty(row)
    if not cells or len(cells) > 3:
        return False
    if any(isinstance(c, (int, float)) and not isinstance(c, bool) for c in cells):
        return False
    return any(to_number(c) is None for c in cells[:1])


def parse_file(path: str) -> Statement:
    st = Statement(path)
    sheets = load_sheets(path)
    st.source = detect_source(sheets)
    st.stated = broker_stated_totals(sheets)
    st.has_identifiers = any(
        "pan" == cell_text(c).lower().strip() or "client name" in cell_text(c).lower()
        for rows in sheets.values() for row in rows[:15] for c in non_empty(row))

    for sheet_name, rows in sheets.items():
        if any(s in sheet_name.lower() for s in SKIP_SHEETS):
            st.skipped_sheets.append(sheet_name)
            continue
        # A sheet name can itself be the section, e.g. "Equity Dividends".
        section = sheet_name
        bucket = match_section(sheet_name)
        mapping: dict[str, list[int]] | None = None
        rows_since_heading = 0

        for row in rows:
            cells = non_empty(row)
            if not cells:
                continue
            text = row_text(row)

            # A header row can be short. Test it before treating a short row as
            # a heading, or a three-column header reads as a section name and
            # every row beneath it is skipped.
            header = map_header(row)
            if header is not None:
                mapping = header
                continue

            if looks_like_heading(row):
                if is_total_label(cells[0]) or is_stated_figure(row):
                    continue
                found = match_section(text)
                # A heading nobody recognises must clear the bucket. Leaving the
                # previous one in force silently taxes the new section at the old
                # section's rate, which is the worst failure this parser has.
                # An unrecognised heading is only worth reporting if rows
                # actually follow it. Every statement opens with a title.
                bucket, section, rows_since_heading = found, text.strip(), 0
                continue

            if is_total_label(cells[0]) or (
                    len(cells) > 1 and is_total_label(cells[1])):
                continue
            if is_stated_figure(row):
                continue
            if mapping is None:
                rows_since_heading += 1
                st.unparsed_sections.append(
                    f"{sheet_name}: data row under {section!r} with no header row")
                continue
            if bucket is None:
                rows_since_heading += 1
                st.unparsed_sections.append(
                    f"{sheet_name}: rows under {section[:60]!r}, a heading this "
                    f"parser does not recognise")
                continue
            rows_since_heading += 1
            st.add(bucket, mapping, row, section, sheet_name)

    st.records = drop_duplicate_views(st)

    # Collapse the noise: one line per distinct problem, with a count.
    seen: dict[str, int] = {}
    for entry in st.unparsed_sections:
        seen[entry] = seen.get(entry, 0) + 1
    st.unparsed_sections = [f"{k} (x{v})" if v > 1 else k for k, v in seen.items()]
    return st


def drop_duplicate_views(st: "Statement") -> list[dict]:
    """Remove a summary view of gains the file also states in detail.

    A Zerodha Tax P&L ships the same realised gains twice: once trade by trade
    on the Tradewise Exits sheet, and again scrip by scrip on the segment
    summary sheet. Reading both doubles every figure in the return — which,
    found on a real file, was this parser reporting 7,348.46 of long-term gain
    where the broker's own summary said 3,674.225.

    Detail and summary are recognised by agreeing on the total, not by sheet
    name, so this holds for brokers whose sheets are named differently. Where
    two views of one bucket disagree, both are kept and the conflict is
    reported: a disagreement means one of them is not a duplicate."""
    by_view: dict[tuple[str, str], list[dict]] = {}
    for rec in st.records:
        by_view.setdefault((rec["bucket"], rec.get("sheet", "")), []).append(rec)

    drop: set[tuple[str, str]] = set()
    buckets = {b for b, _ in by_view}
    for bucket in buckets:
        views = [(sheet, rows) for (b, sheet), rows in by_view.items() if b == bucket]
        if len(views) < 2:
            continue
        views.sort(key=lambda v: -len(v[1]))
        keep_sheet, keep_rows = views[0]
        keep_total = sum(r.get("gain") or 0 for r in keep_rows)
        for sheet, rows in views[1:]:
            total = sum(r.get("gain") or 0 for r in rows)
            same = abs(total - keep_total) <= max(1.0, abs(keep_total) * 0.005)
            if same:
                drop.add((bucket, sheet))
                st.dropped_views.append(
                    f"{bucket}: {sheet!r} restates the same {total:,.2f} that "
                    f"{keep_sheet!r} gives in {len(keep_rows)} rows. Counted once.")
            else:
                st.warnings.append(
                    f"{bucket}: {sheet!r} totals {total:,.2f} but {keep_sheet!r} "
                    f"totals {keep_total:,.2f} over {len(keep_rows)} rows. Two "
                    f"views of one bucket that disagree — both are counted above, "
                    f"so check which one belongs on the return before filing.")
    return [r for r in st.records
            if (r["bucket"], r.get("sheet", "")) not in drop]


# ------------------------------------------------------------------ resolution

RESOLVERS = {
    "mf_unknown": (
        "Mutual fund, equity-oriented or not?",
        "Equity-oriented means the scheme holds 65% or more in domestic equity. "
        "It decides 111A/112A (20% / 12.5% with a 1,25,000 exemption) against "
        "slab or 112. Section headings never say. Check the scheme's factsheet, "
        "or cross-check AIS: SFT-18-EMF with non-zero STT is equity-oriented, "
        "SFT-18-OTU with zero STT is not. Arbitrage funds are equity-oriented; "
        "balanced-advantage, liquid and debt funds usually are not."),
    "nonequity_unknown": (
        "Non-equity: is this a specified mutual fund under s.50AA?",
        "Units of a specified mutual fund (broadly, 65%+ in debt) are deemed "
        "SHORT term however long they were held, and taxed at slab rates. "
        "Everything else non-equity held beyond its threshold is 112 at 12.5%."),
    "stcg_unknown": (
        "Short-term: was STT paid on an equity or equity-MF sale?",
        "STT paid puts it in 111A at 20%. Anything else is slab."),
    "ltcg_unknown": (
        "Long-term: was STT paid on an equity or equity-MF sale?",
        "STT paid puts it in 112A at 12.5% with the 1,25,000 exemption. "
        "Anything else is 112 at 12.5% with no exemption."),
    "unlisted_unknown": (
        "Unlisted or delisted shares: how long were they held?",
        "No STT is paid on an unlisted transfer, so 111A and 112A do not apply. "
        "Held over 24 months it is 112 at 12.5% with no 1,25,000 exemption; "
        "under 24 months it is slab. Unlisted shares also make Schedule AL "
        "mandatory content and force ITR-2 or ITR-3."),
    "foreign_unknown": (
        "Foreign shares or overseas holdings — this is an escalate case.",
        "Foreign assets bring Schedule FA, Schedule FSI and Schedule TR, a filing "
        "obligation regardless of income under the fourth proviso to s.139(1), "
        "and Black Money Act exposure for an omission. This skill does not cover "
        "them. Route to a qualified professional."),
    "landbuilding_unknown": (
        "Land or building: when was it acquired?",
        "Acquired before 23 July 2024 and transferred on or after, a resident "
        "individual or HUF pays the LOWER of 12.5% without indexation and 20% "
        "with indexation, under the second proviso to s.112(1)(a). Both the "
        "indexed and the unindexed gain are needed before any figure is possible. "
        "compute_tax.py refuses without them for the same reason."),
    "buyback": (
        "Buyback on or after 1 October 2024?",
        "If so the whole consideration is a deemed dividend under s.2(22)(f), "
        "taxable as Other Sources at slab rates, and s.46A deems the capital-gains "
        "consideration NIL — so the entire cost becomes a capital loss. Do not "
        "report it as an ordinary sale."),
}


# Schedule CG item F, and Schedule OS for dividends, want the year split into
# these five windows. They are the s.234C advance-tax instalment dates, which is
# why the last one is a fortnight long.
QUARTERS = [
    ("upto_15_jun", "01-Apr-2025 to 15-Jun-2025", "2025-06-15"),
    ("16_jun_to_15_sep", "16-Jun-2025 to 15-Sep-2025", "2025-09-15"),
    ("16_sep_to_15_dec", "16-Sep-2025 to 15-Dec-2025", "2025-12-15"),
    ("16_dec_to_15_mar", "16-Dec-2025 to 15-Mar-2026", "2026-03-15"),
    ("16_mar_to_31_mar", "16-Mar-2026 to 31-Mar-2026", "2026-03-31"),
]


def quarterly_split(records: list[dict]) -> dict:
    """Capital gains by the five ITR windows, from each row's date of sale.

    Schedule CG item F is mandatory and is transcribed by hand from a broker
    statement more often than anything else on the form. Getting it wrong does
    not change the tax but it does change s.234C interest, and the portal will
    not compute it for you."""
    out: dict[str, dict] = {}
    undated = 0
    for rec in records:
        sold = rec.get("sell_date")
        gain = rec.get("gain") if rec.get("gain") is not None else rec.get("amount")
        if gain is None:
            continue
        if not sold:
            undated += 1
            continue
        for key, label, end in QUARTERS:
            if sold <= end:
                slot = out.setdefault(key, {"window": label, "gain": 0.0, "rows": 0})
                slot["gain"] += gain
                slot["rows"] += 1
                break
        else:
            undated += 1
    for slot in out.values():
        slot["gain"] = round(slot["gain"], 2)
    if undated:
        out["undated"] = {"window": "no readable date of sale", "rows": undated,
                          "gain": 0.0,
                          "note": "assign these by hand before filling item F"}
    return out


def summarise(statements: list[Statement]) -> dict:
    # Tag by position, not by filename: the same path given twice is two
    # statements, and counting it once would hide a real double-count.
    for i, st in enumerate(statements):
        for rec in st.records:
            rec["_statement"] = i
    records = [r for st in statements for r in st.records]
    buckets: dict[str, dict] = {}
    needs: dict[str, dict] = {}

    for rec in records:
        b = rec["bucket"]
        target = needs if b in RESOLVERS else buckets
        entry = target.setdefault(b, {"rows": 0, "gain": 0.0, "sell_value": 0.0,
                                      "buy_value": 0.0, "records": []})
        entry["rows"] += 1
        for f in ("gain", "sell_value", "buy_value"):
            if rec.get(f) is not None:
                entry[f] += rec[f]          # rounded once, at the end
        if b == "dividend" and rec.get("amount") is not None:
            entry["gain"] += rec["amount"]
        entry["records"].append(rec)

    for entry in list(buckets.values()) + list(needs.values()):
        for f in ("gain", "sell_value", "buy_value"):
            entry[f] = round(entry[f], 2)

    for b, entry in buckets.items():
        meta = BUCKETS.get(b, {})
        entry["schedule"] = meta.get("schedule", "unclassified")
        entry["label"] = meta.get("label", b)
        if b in ("111A", "112A", "112", "stcg_slab", "dividend"):
            entry["quarterly"] = quarterly_split(entry["records"])
    for b, entry in needs.items():
        q, why = RESOLVERS[b]
        entry["question"] = q
        entry["why_it_matters"] = why

    checks: list[str] = []
    flags: list[str] = []

    if any("quarterly" in e for e in buckets.values()):
        checks.append(
            "Each capital-gains bucket carries a quarterly split, keyed on the "
            "date of sale. Schedule CG item F wants exactly those five windows, "
            "and Schedule OS wants the same for dividends. It does not change the "
            "tax, but it does change s.234C interest, and the portal will not "
            "work it out for you.")

    if "112A" in buckets:
        gross = buckets["112A"]["gain"]
        checks.append(
            f"112A gains total {gross:,.2f} before the 1,25,000 exemption. That "
            "exemption is once per PAN for the year, not once per broker or per "
            "statement — add every source together before applying it.")
        if any(r.get("fmv") for r in buckets["112A"]["records"]):
            checks.append(
                "Some 112A rows carry a fair market value, so the broker has "
                "already applied 31-Jan-2018 grandfathering and the stated gain "
                "is the taxable one. Do not recompute the cost.")
        checks.append(
            "Schedule 112A needs a scrip-wise breakdown, so keep the per-row "
            "detail — see references/portal-traps.md for the CSV upload rules.")

    if "speculative" in buckets or "fno" in buckets:
        flags.append(
            "Intraday or F&O activity is present, so this is business income and "
            "the return is ITR-3, not ITR-1/2 — however small the amount. "
            "Schedule BP, Balance Sheet and P&L all become mandatory.")
    if "speculative" in buckets and "fno" in buckets:
        checks.append(
            "Speculative (intraday) and non-speculative (F&O) losses do not mix. "
            "A speculative loss can only be set off against speculative income, "
            "and carries forward 4 years, not 8.")
    if "foreign_unknown" in needs:
        flags.append(
            "Foreign or overseas holdings are present. That brings Schedule FA, "
            "Schedule FSI and Schedule TR, a filing obligation regardless of "
            "income under the fourth proviso to s.139(1), and Black Money Act "
            "exposure for an omission. This is an escalate case — route to a "
            "qualified professional rather than filing from this output.")
    if "landbuilding_unknown" in needs:
        flags.append(
            "Land or building is present. Acquired before 23 July 2024 and sold "
            "on or after, a resident individual or HUF pays the LOWER of 12.5% "
            "without indexation and 20% with indexation. Both figures are needed "
            "before any tax number is possible.")
    if "buyback" in needs:
        flags.append("A buyback row is present. Buybacks on or after 1 October "
                     "2024 are taxed as dividends, not capital gains.")

    losses = [b for b, e in buckets.items() if e["gain"] < 0]
    if losses:
        checks.append(
            f"Net loss in {', '.join(losses)}. Carrying a loss forward requires "
            "the return to be filed by the s.139(1) due date (s.80) and Schedules "
            "CYLA, BFLA and CFL to be completed. compute_tax.py refuses on losses "
            "rather than guessing the set-off order.")

    # A bucket whose consideration is short of its row count will understate the
    # full value of consideration on Schedule CG, which is a separate figure from
    # the gain and is checked against AIS.
    for b, entry in buckets.items():
        stated = sum(1 for r in entry["records"] if r.get("sell_value") is not None)
        if b != "dividend" and stated < entry["rows"]:
            checks.append(
                f"{b}: {entry['rows'] - stated} of {entry['rows']} rows stated no "
                "sale value, so the consideration total is short by those rows. "
                "Schedule CG asks for full value of consideration separately from "
                "the gain, and AIS is reconciled against consideration.")

    # Row-level flags are easy to lose in a 400-row file, so they surface as counts.
    tallies: dict[str, int] = {}
    for rec in records:
        for f in rec.get("flags", []):
            key = f.split(";")[0]
            tallies[key] = tallies.get(key, 0) + 1
    for message, count in sorted(tallies.items(), key=lambda kv: -kv[1]):
        checks.append(f"{count} row(s): {message}")

    # The same trade in two files, or in a summary sheet and a detail sheet of one
    # workbook, doubles a bucket silently.
    # Two identical trades in one statement are ordinary — the same scrip sold
    # twice at the same price on the same day. The same row in two files is not.
    seen: dict[tuple, set] = {}
    for rec in records:
        key = (str(rec.get("name")).upper(), rec.get("buy_date"), rec.get("sell_date"),
               rec.get("quantity"), rec.get("sell_value"), rec.get("gain"))
        if key[0] == "NONE":
            continue
        seen.setdefault(key, set()).add(rec.get("_statement"))
    dupes = {k: len(v) for k, v in seen.items() if len(v) > 1}
    if dupes:
        flags.append(
            f"{len(dupes)} identical row(s) appear in more than one of the files "
            f"given — "
            f"{', '.join(k[0] for k in list(dupes)[:5])}"
            f"{'...' if len(dupes) > 5 else ''}. Totals above count each copy. "
            "Passing both a tax P&L and a tradewise export of the same account, or "
            "the same file twice, does this.")

    # Reconcile against what the statement says about itself.
    for st in statements:
        for bucket, stated in sorted(st.stated.items()):
            got = (buckets.get(bucket) or needs.get(bucket) or {}).get("gain")
            if got is None:
                if abs(stated) > 0.005:
                    flags.append(
                        f"{st.file}: the statement's own summary reports "
                        f"{stated:,.2f} under {bucket}, and no rows were parsed "
                        f"into it. Something was missed — run --inspect.")
                continue
            if abs(got - stated) > max(1.0, abs(stated) * 0.001):
                flags.append(
                    f"{st.file}: {bucket} totals {got:,.2f} from the rows, but the "
                    f"statement's own summary says {stated:,.2f}. Find the "
                    f"difference before this figure reaches a return.")
            else:
                checks.append(
                    f"{st.file}: {bucket} ties to the statement's own summary "
                    f"({stated:,.2f}).")
        if st.has_identifiers:
            checks.append(
                f"{st.file} carries a PAN and an account holder's name in its "
                "header rows. Nothing here reproduces them, but do not paste the "
                "file, or a screenshot of it, into a public issue.")

    for st in statements:
        for note in st.dropped_views:
            checks.append(f"{st.file}: {note}")
        for warning in st.warnings:
            flags.append(f"{st.file}: {warning}")
        if st.skipped_sheets:
            checks.append(
                f"{st.file}: skipped {', '.join(repr(s) for s in st.skipped_sheets)} "
                "— open positions are unrealised and not income; charges and ledger "
                "balances are not gains.")
        if st.unparsed_sections:
            flags.append(
                f"{st.file}: {len(st.unparsed_sections)} row group(s) were skipped "
                "because the heading or the header row was not recognised. Nothing "
                "was guessed at, but nothing was counted either — run --inspect and "
                "check what was lost:\n    " + "\n    ".join(st.unparsed_sections[:8]))

    return {
        "buckets": buckets,
        "needs_confirmation": needs,
        "checks": checks,
        "flags": flags,
    }


def inspect(path: str) -> None:
    sheets = load_sheets(path)
    print(f"{safe_name(path)} — {len(sheets)} sheet(s), "
          f"detected source: {detect_source(sheets)}\n")
    for name, rows in sheets.items():
        print(f"  [{name}] {len(rows)} rows")
        for i, row in enumerate(rows[:40]):
            cells = non_empty(row)
            if not cells:
                continue
            kind = ""
            if len(cells) == 1:
                kind = f"  <- heading, matched: {match_section(row_text(row))}"
            elif map_header(row) is not None:
                kind = f"  <- header, fields: {sorted(map_header(row))}"
            print(f"    {i:>3}: {row_text(row)[:100]}{kind}")
        if len(rows) > 40:
            print(f"    ... {len(rows) - 40} more rows")
        print()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help=".xlsx or .csv statements")
    ap.add_argument("--json", metavar="PATH", help="write the full result to a file")
    ap.add_argument("--inspect", action="store_true",
                    help="print the sheet structure instead of parsing — use this "
                         "when a broker layout is not recognised")
    ap.add_argument("--rows", action="store_true", help="include every parsed row in stdout")
    a = ap.parse_args(argv)

    if a.inspect:
        for path in a.files:
            try:
                inspect(path)
            except SpreadsheetError as e:
                print(f"{path}: {e}", file=sys.stderr)
                return 2
        return 0

    statements = []
    for path in a.files:
        try:
            statements.append(parse_file(path))
        except SpreadsheetError as e:
            print(json.dumps({"refused": str(e)}, indent=2), file=sys.stderr)
            return 2

    result = summarise(statements)
    result["sources"] = [{"file": st.file, "detected": st.source,
                          "rows_parsed": len(st.records)} for st in statements]
    result["disclaimer"] = (
        "Parsed from the statement as given. It reconciles the statement to "
        "Schedule CG; it does not verify the statement. Tie every figure back to "
        "AIS before filing, and remember AIS silence does not prove absence.")

    if not any(st.records for st in statements):
        result["refused"] = (
            "No rows were recognised in any file. Run with --inspect to see the "
            "layout, and open an issue with the sheet names and header row (no "
            "amounts, no identifiers) so the layout can be added.")
        print(json.dumps(result, indent=2), file=sys.stderr)
        return 2

    if not a.rows:
        for entry in list(result["buckets"].values()) + list(result["needs_confirmation"].values()):
            entry["sample"] = entry["records"][:3]
            entry["records"] = f"{len(entry['records'])} rows — pass --rows or --json to see them"

    print(json.dumps(result, indent=2))

    if a.json:
        full = summarise(statements)
        full["sources"] = result["sources"]
        with open(a.json, "w") as fh:
            json.dump(full, fh, indent=2)
        print(f"\nfull detail written to {a.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
