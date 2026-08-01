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
from redact import MASK, safe_name, strip_identifiers  # noqa: E402
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

    # The bond names itself, and its question is not the s.50AA one. It has to
    # win over the generic non-equity rules, which a heading like
    # "Non Equity - Sovereign Gold Bond" would otherwise match first.
    (("sovereign gold",), (), "sgb_unknown"),
    (("gold bond",), (), "sgb_unknown"),
    (("sgb",), (), "sgb_unknown"),

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

# A Schedule 112A CSV is an upload template for the income-tax portal, not a
# broker statement. Require a compound signature made of the portal's numbered
# fields and derived-column formulas: no genuine broker Tax P&L should reproduce
# all three exact headings, while a single generic money heading could collide.
SCHEDULE_112A_HEADER_SIGNATURE = {
    "share/unit acquired(1a)",
    "total deductions(13) = 7 + 12",
    "balance(14) = 6 - 13",
}

# A detected brand is not a validated layout. Add a source label here only
# after a real specimen has been inspected, an identifier-free synthetic fixture
# has been built from that layout, and exact-output assertions pin its buckets,
# row counts and gains. A file merely parsing without error earns nothing.
VALIDATED_BROKER_LAYOUTS = frozenset({"zerodha"})

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


def map_header(row: list) -> dict[str, object] | None:
    """Return {field: [candidate column indices]} if this row is a header row.

    Every candidate is kept rather than the first match, because a decoy column
    ahead of the real one silently poisons the whole bucket: a text column
    headed "Nature of Gain" ahead of "Realised P&L" produced a bucket reading
    zero, with one row in it and no complaint."""
    mapping: dict[str, list[tuple[int, int]]] = {}
    gain_labels: list[tuple[int, int, str]] = []
    for idx, cell in enumerate(row):
        text = cell_text(cell).lower()
        if not text or len(text) > 60:
            continue
        if any(d in text for d in DECOY_WORDS):
            continue
        for needle, field in HEADER_RULES:
            if needle in text:
                mapping.setdefault(field, []).append((len(needle), idx))
                if field == "gain":
                    gain_labels.append((len(needle), idx, needle))
                break
    # A header row has to identify the instrument and at least one number.
    if "name" not in mapping or not (set(mapping) &
                                     {"gain", "sell_value", "amount", "quantity"}):
        return None
    # Most specific header first. Zerodha prints "Profit" before "Taxable
    # Profit"; the second is the grandfathered figure that belongs on the return,
    # so leftmost-wins would quietly use the pre-grandfathering number.
    out = {field: [idx for _, idx in sorted(hits, key=lambda h: (-h[0], h[1]))]
           for field, hits in mapping.items()}
    # Preserve the label for every gain candidate, not just the preferred one.
    # A blank Taxable Profit cell falls back to Profit on that row, so safety
    # depends on the candidate actually selected rather than the header order.
    if gain_labels:
        out["__gain_labels"] = {idx: label for _, idx, label in gain_labels}
    return out


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

    def add(self, bucket: str, mapping: dict[str, object], row: list,
            section: str, sheet: str = ""):
        rec: dict = {"file": self.file, "sheet": sheet, "section": section,
                     "bucket": bucket}
        gain_labels = mapping.get("__gain_labels") or {}
        for field, candidates in mapping.items():
            if field.startswith("__"):
                continue
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
                    if (field == "gain" and "taxable" in
                            gain_labels.get(idx, "").lower()):
                        rec["gain_carries_grandfathering"] = True
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


def is_schedule_112a_upload_template(sheets: dict[str, list[list]]) -> bool:
    """Recognise the portal upload schema without depending on byte quirks.

    check_112a_csv.py performs the full byte/header/row validation. This check
    only keeps that specialised input from being mistaken for a broker Tax P&L.
    """
    for rows in sheets.values():
        for row in rows[:10]:
            headings = {
                re.sub(r"\s+", " ", cell_text(cell).replace("\u00a0", " "))
                .strip().lower()
                for cell in row
                if cell_text(cell).strip()
            }
            if SCHEDULE_112A_HEADER_SIGNATURE <= headings:
                return True
    return False


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
    if is_schedule_112a_upload_template(sheets):
        raise SpreadsheetError(
            f"{st.file}: this is a Schedule 112A portal upload template, not a "
            "broker Tax P&L. Refused rather than deriving capital-gains figures "
            "from it; run check_112a_csv.py on this file instead.")
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

# The buckets item F is about. Intraday and F&O are Schedule BP business income,
# so putting them in the item F shape invites a reader to file them on the wrong
# schedule entirely.
SCHEDULE_CG_BUCKETS = frozenset(
    {"111A", "112A", "112", "stcg_slab", "dividend"})

# Buckets whose amounts are not known to be rupees. Nothing here converts a
# currency, so printing a rupee sign in front of one would be a guess at the
# unit, on a figure the parser already says it cannot use.
NON_RUPEE_BUCKETS = frozenset({"foreign_unknown"})

# Unresolved buckets that are still capital gains: answering moves them between
# Schedule CG rate rows rather than off the schedule. Their per-section splits
# are worth keeping, because a non-equity bucket holding both a short-term and a
# long-term section will land on two different rate rows.
# `[documented]` schedule-sections.md records that Schedule CG Table F wants
# figures net of current-year and brought-forward set-off, each row equal to the
# corresponding Schedule BFLA figure, and that it does not accept negatives.
# What this parser can produce is therefore timing, not Table F input: it knows
# the dates of sale and the gross figures, and it cannot know the set-off.
QUARTERLY_BASIS = (
    "By date of sale, before any statutory set-off. Where a window holds both "
    "gains and losses the figure is their NET and `gains` and `losses` carry "
    "the two sides — the netting inside a window is arithmetic on the "
    "statement, not the set-off the return performs. [documented] Schedule CG "
    "Table F takes figures NET of current-year and brought-forward set-off, "
    "each row equal to the corresponding Schedule BFLA figure, and it does not "
    "accept negatives — so fill Table F last, from BFLA, not from these "
    "numbers. [documented] s.234C is charged on the shortfall in each advance-"
    "tax instalment, so it turns on when a gain arose. [inferred] That makes "
    "this split useful for the s.234C working specifically, which is the one "
    "thing Schedule BFLA cannot tell you.")

# `[documented]` A dividend is Other Sources, not a capital gain, so none of the
# Table F set-off machinery applies to it. `[documented]` s.234C is charged on
# the shortfall in each advance-tax instalment, and the proviso that spares a
# filer for an underestimated capital gain extends to dividend income, so the
# quarter a dividend fell in is what the working needs.
DIVIDEND_BASIS = (
    "Gross, keyed on the EX-DATE, because that is the only date a broker "
    "statement carries. [documented] This is Other Sources, not a capital "
    "gain: Schedule CG Table F, Schedule BFLA and the set-off ordering have "
    "nothing to do with it. [documented] Schedule OS wants the quarter of "
    "actual RECEIPT, and a dividend is received days or weeks after its "
    "ex-date — so where the two straddle a 15 June, 15 September, 15 December "
    "or 15 March boundary this row is in the wrong window and must be moved. "
    "[documented] That matters because s.234C is charged on the shortfall in "
    "each advance-tax instalment. Check the bank credit before using this for "
    "a s.234C working.")

# `[documented]` s.55(2)(ac) grandfathers an equity acquisition made on or
# before 31 January 2018: the cost becomes the higher of actual cost and the
# 31 January 2018 fair market value, capped at the sale consideration. A raw
# Profit column does not carry that; reading-documents.md records that the
# `Taxable Profit` column exists precisely because it does.
GRANDFATHER_CUTOFF = "2018-01-31"

# Buckets that can reach Schedule 112A, where the cutoff applies. STCG can
# resolve only to s.111A or slab rates, never s.112A.
POSSIBLY_112A_BUCKETS = frozenset({"112A", "mf_unknown", "ltcg_unknown"})


def can_reach_112a(bucket: str, rec: dict) -> bool:
    """Whether this particular record, rather than its bucket, can reach 112A."""
    if bucket not in POSSIBLY_112A_BUCKETS:
        return False
    # A mutual-fund bucket is otherwise unresolved, but its own section can
    # already establish short-term treatment. Such a row cannot be 112A.
    section = str(rec.get("section") or "").lower()
    return not (bucket == "mf_unknown"
                and any(label in section
                        for label in ("short term", "short-term", "stcg")))


# An amount-sensitive instrument may be named in the ROW rather than the
# section heading — a "Non Equity - Long Term" section holding "SGB 2032". The
# heading classifies the bucket and is never revisited, so the row name is the
# only place that evidence survives.
AMOUNT_SENSITIVE_INSTRUMENTS = (
    ("sovereign gold", "a sovereign gold bond, whose redemption with the RBI "
                       "is not a transfer at all under s.47(viic)"),
    ("gold bond", "a sovereign gold bond, whose redemption with the RBI is not "
                  "a transfer at all under s.47(viic)"),
    ("sgb", "a sovereign gold bond, whose redemption with the RBI is not a "
            "transfer at all under s.47(viic)"),
)


def amount_sensitive_rows(records: list[dict]) -> list[tuple[int, str]]:
    """Rows whose instrument name says the amount is not settled.

    Returns (count, why) pairs. A bucket classified from a generic heading can
    still hold an instrument that names itself, and that name is evidence the
    heading did not carry."""
    found: list[tuple[int, str]] = []
    for marker, why in AMOUNT_SENSITIVE_INSTRUMENTS:
        rows = sum(1 for rec in records
                   if marker in str(rec.get("name") or "").lower())
        if rows:
            found.append((rows, why))
            break
    return found


def grandfathering_unsettled(bucket: str, records: list[dict]) -> int:
    """Rows whose gain could move if the bucket resolves to 112A.

    A pre-cutoff acquisition whose selected gain is not Taxable Profit is not
    settled by an FMV cell alone: this parser neither applies s.55(2)(ac) nor
    proves that the broker used the FMV. Resolving the bucket as equity-oriented
    can still change it. Publishing a quarterly split of a number about to move
    is the same mistake as publishing a buyback's."""
    unsettled = 0
    for rec in records:
        if not can_reach_112a(bucket, rec):
            continue
        if rec.get("gain_carries_grandfathering"):
            continue          # read from Taxable Profit; already adjusted
        bought = rec.get("buy_date")
        # An absent date is not evidence of a post-cutoff acquisition. Only a
        # date proven later than the cutoff settles it.
        if bought and bought > GRANDFATHER_CUTOFF:
            continue
        unsettled += 1
    return unsettled


def grandfathering_missing_date_count(bucket: str, records: list[dict]) -> int:
    """Count unsettled rows whose acquisition date is absent, not pre-cutoff."""
    return sum(1 for rec in records
               if can_reach_112a(bucket, rec)
               and not rec.get("gain_carries_grandfathering")
               and not rec.get("buy_date"))


UNRESOLVED_CG_BUCKETS = frozenset(
    {"nonequity_unknown", "mf_unknown", "stcg_unknown", "ltcg_unknown",
     "unlisted_unknown"})

# Buckets whose figures are not a Schedule CG amount yet — because resolving the
# question changes the amount, or because the amount is not in rupees. For these
# the dates are known but the figures are not, so no quarterly split is
# published until the question is answered. Generic short/long-term and
# non-equity headings do not establish an asset class: they could conceal land,
# an unlisted share, a buyback, a foreign holding, or an SGB, each of which can
# change the broker figure.
#
# `[documented]` A buyback on or after 1 October 2024 makes the whole
# consideration a deemed dividend under s.2(22)(f), and s.46A deems the
# capital-gains consideration nil, so the entire cost becomes a capital loss —
# the broker's gain is not the figure Schedule CG carries.
# `[documented]` Land or building acquired before 23 July 2024 and transferred
# on or after it is charged at the LOWER of 12.5% unindexed and 20% indexed
# under the second proviso to s.112(1)(a), so no figure exists until the indexed
# gain is supplied.
# `[observed] 2026-07-31, repository search: nothing here converts a foreign
# currency, and the foreign resolver says foreign holdings are out of scope, so
# a foreign broker's gain would be published in its native currency as though it
# were a rupee filing figure.
# `[documented]` s.47(viic) provides that redemption of a Sovereign Gold Bond by
# an individual is not a transfer, so no capital gain arises at all — while a
# sale of the same bond on the exchange is an ordinary transfer. A broker
# statement does not distinguish the two, and the s.50AA question the non-equity
# bucket asks cannot resolve it either.
# `[documented]` s.50CA can substitute fair market value for consideration on
# an unlisted-share transfer. The broker profit is not final until that value is
# known; see references/schedule-sections.md for the corresponding return field.
# Only where the ANSWER changes the amount, or the amount is not in rupees.
#
# The distinction this set exists to draw is between a question about the RATE
# and a question about the AMOUNT. A buyback's consideration becomes a deemed
# dividend and its capital result a loss of the whole cost; land may need an
# indexed gain before any figure exists; a foreign figure is in units this
# reader does not parse; a sovereign gold bond may be a redemption that is not
# a transfer at all. In each of those the number itself moves, so no window can
# be published for it.
#
# A bare "Short Term" or "Long Term" heading names no asset at all, so it could
# be any of those — nothing has been ruled out and the amount is as open as the
# rate. `[documented]` And s.50CA deems the fair market value to be the
# consideration where unlisted shares are transferred below it, so an unlisted
# bucket's figure can move too. Those three withhold for the same reason.
#
# What is left publishes: a heading that NAMES its asset class and leaves only a
# rate question open. `[documented]` s.50AA decides whether a non-equity fund is
# a specified mutual fund, which changes the rate and the holding period, not
# the figure. Those windows are what a s.234C working needs and what Schedule
# BFLA cannot supply, and withholding them left the hand arithmetic this parser
# exists to prevent.
#
# `[inferred]` A named non-equity or mutual-fund heading is treated as ruling
# out a buyback, land or a bond, because a broker that sold one says so — and
# the sovereign-gold-bond rules above match first for exactly that reason. The
# published windows carry a basis saying they are gross timing and not an
# amount for any schedule, which is what makes publishing them honest rather
# than a guess about the figure.
#
# The one case that crosses over — a pre-2018 acquisition that could resolve to
# 112A and take grandfathering with it — is not a property of the bucket and is
# checked per row instead, by grandfathering_unsettled().
QUARTERLY_NOT_PUBLISHABLE = frozenset(
    {"buyback", "landbuilding_unknown", "foreign_unknown", "sgb_unknown",
     "unlisted_unknown", "stcg_unknown", "ltcg_unknown"})

RESOLVERS = {
    "sgb_unknown": (
        "Sovereign Gold Bond: was this redeemed with the RBI, or sold on the "
        "exchange?",
        "[documented] s.47(viic) provides that redemption of a Sovereign Gold "
        "Bond by an individual is not a transfer, so no capital gain arises and "
        "the broker's profit figure is not taxable at all. A sale on the "
        "exchange is an ordinary transfer and is taxable. [observed] A broker "
        "statement does not say which happened, and the two produce completely "
        "different returns, so nothing here is totalled until you say."),
    "mf_unknown": (
        "Mutual fund, equity-oriented or not?",
        "Equity-oriented means the scheme holds 65% or more in domestic equity. "
        "It decides 111A/112A (20% / 12.5% with a 1,25,000 exemption) against "
        "slab or 112. Section headings never say. Check the scheme's factsheet, "
        "or cross-check AIS: SFT-18-EMF with non-zero STT is equity-oriented, "
        "SFT-18-OTU with zero STT is not. Arbitrage funds are equity-oriented; "
        "balanced-advantage, liquid and debt funds usually are not."),
    "nonequity_unknown": (
        "Non-equity: what asset or transaction is this?",
        "[observed] A generic non-equity heading does not distinguish a "
        "specified mutual fund, a Sovereign Gold Bond redemption, or another "
        "asset. [documented] Units of a specified mutual fund (broadly, 65%+ "
        "in debt) are deemed SHORT term however long they were held and taxed "
        "at slab rates. [inferred] Another asset can have a different head, "
        "rate, or amount calculation. See references/schedule-sections.md, "
        "\"s.50AA classification\", which sets out the s.50AA test for gold, "
        "liquid and debt ETFs. It gives the ITR row where s.50AA applies; "
        "where it does not, the holding period is itself unsettled and the "
        "row has to be established against a primary source."),
    "stcg_unknown": (
        "Short-term: what asset was sold, and was STT paid if it was equity?",
        "[observed] A generic short-term heading does not establish the "
        "asset. [documented] s.111A charges a short-term gain on an equity "
        "share or a unit of an equity-oriented fund at 20% where STT is paid "
        "on the transfer. [inferred] Anything outside that section can differ "
        "in head, rate or the calculation of the amount itself, so the rate "
        "cannot be chosen until the asset is known."),
    "ltcg_unknown": (
        "Long-term: what asset was sold, and was STT paid if it was equity?",
        "[observed] A bare long-term heading does not establish the asset. "
        "[documented] s.112A charges a long-term gain on an equity share or a "
        "unit of an equity-oriented fund at 12.5% above 1,25,000 where STT is "
        "paid. [inferred] Land, unlisted shares and other assets can need a "
        "different calculation of the amount before any rate applies."),
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
# The first window's test is `sold <= 15 June 2025`, which is also true of every
# date before the year began. A statement for the wrong financial year would
# otherwise have its whole prior-year gain reported inside the first instalment
# window — a plausible, wrong s.234C working.
FY_START = "2025-04-01"
FY_END = "2026-03-31"

QUARTERS = [
    ("upto_15_jun", "01-Apr-2025 to 15-Jun-2025", "2025-06-15"),
    ("16_jun_to_15_sep", "16-Jun-2025 to 15-Sep-2025", "2025-09-15"),
    ("16_sep_to_15_dec", "16-Sep-2025 to 15-Dec-2025", "2025-12-15"),
    ("16_dec_to_15_mar", "16-Dec-2025 to 15-Mar-2026", "2026-03-15"),
    ("16_mar_to_31_mar", "16-Mar-2026 to 31-Mar-2026", "2026-03-31"),
]


def out_of_year_exception(records: list[dict], *, amount_is_usable: bool = True) -> dict | None:
    """Return date scope even when an exception amount is unreadable or unusable."""
    rows = 0
    gain = 0.0
    unread_amount_rows = 0
    for rec in records:
        sold = rec.get("sell_date")
        amount = rec.get("gain") if rec.get("gain") is not None else rec.get("amount")
        if sold and (sold < FY_START or sold > FY_END):
            rows += 1
            if amount is None:
                unread_amount_rows += 1
            else:
                gain += amount
    if not rows:
        return None
    exception = {
        "window": f"sold outside {FY_START} to {FY_END}",
        "rows": rows,
        "note": "These rows are dated outside the financial year this "
                "parser splits. They are in no instalment window for it, "
                "so they are in no instalment window for it. [inferred] "
                "That usually means the statement covers another year, but "
                "a multi-year export or a misparsed date would look the "
                "same. Check which year the file covers before using "
                "anything above it."}
    if amount_is_usable and not unread_amount_rows:
        exception["gain"] = round(gain, 2)
    elif unread_amount_rows:
        exception["amount_unreadable_rows"] = unread_amount_rows
    return exception


def quarterly_withholding_reason(bucket: str, records: list[dict],
                                 unreadable_gain_rows: int = 0) -> str | None:
    """Why a dated bucket still cannot safely publish a quarterly amount."""
    reasons = []
    if unreadable_gain_rows:
        reasons.append(
            f"{unreadable_gain_rows} row(s) here have no readable gain. No "
            "split is published because a partial timing amount would understate "
            "the s.234C working. Get the statement's gain or Taxable Profit "
            "value before using any dated amount.")
    grandfathered = grandfathering_unsettled(bucket, records)
    if grandfathered:
        missing_dates = grandfathering_missing_date_count(bucket, records)
        date_evidence = (
            f"{missing_dates} of them have no readable acquisition date; "
            "the parser does not know which side of the cutoff they fall on. "
            if missing_dates else
            f"All {grandfathered} were acquired on or before "
            f"{GRANDFATHER_CUTOFF}. ")
        reasons.append(
            f"{grandfathered} row(s) here need a grandfathering check. "
            + date_evidence +
            "Their selected gain is not Taxable Profit; an FMV value alone "
            "does not show that the 31 January 2018 fair market value was "
            "used. [documented] "
            "s.55(2)(ac) grandfathers an equity acquisition made by then — "
            "the cost becomes the higher of actual cost and that day's fair "
            "market value, capped at the sale consideration — so the gain can "
            "change. No split "
            "is published while the amount can still move. Get the "
            "statement's Taxable Profit column, which carries it.")
    for rows, why in amount_sensitive_rows(records):
        reasons.append(
            f"{rows} row(s) here are named as {why}. [observed] The section "
            "heading classified this bucket and is never revisited, so the "
            "instrument name is the only place that shows up — and it means "
            "the figure may not be a gain at all. No split is published until "
            "the asset and the transaction are established.")
    if bucket in QUARTERLY_NOT_PUBLISHABLE:
        reasons.append(
            "The windows are not published for this bucket: the figures are "
            "not a Schedule CG amount yet, because answering the question "
            "above changes the amount rather than only the rate, or because "
            "the amount is not in rupees. Any split shown now would be of a "
            "figure the return will not carry. This script takes no answer "
            "to that question and re-running it will report the same "
            "bucket, so carry the dated rows above into whatever settles "
            "it — your working papers, or a professional.")
    return " ".join(reasons) or None


def quarterly_split(records: list[dict]) -> dict:
    """Capital gains by the five ITR windows, from each row's date of sale.

    Schedule CG item F is mandatory and is transcribed by hand from a broker
    statement more often than anything else on the form. Getting it wrong does
    not change the tax but it does change s.234C interest, and the portal will
    not compute it for you."""
    out: dict[str, dict] = {}
    undated = 0
    undated_gain = 0.0
    for rec in records:
        sold = rec.get("sell_date")
        gain = rec.get("gain") if rec.get("gain") is not None else rec.get("amount")
        if gain is None:
            continue
        if not sold:
            undated += 1
            undated_gain += gain
            continue
        if sold < FY_START or sold > FY_END:
            continue
        for key, label, end in QUARTERS:
            if sold <= end:
                slot = out.setdefault(key, {"window": label, "gain": 0.0, "rows": 0})
                slot["gain"] += gain
                slot["rows"] += 1
                if gain > 0:
                    slot["gains"] = round(slot.get("gains", 0.0) + gain, 2)
                elif gain < 0:
                    slot["losses"] = round(slot.get("losses", 0.0) + gain, 2)
                break
        else:
            undated += 1
            undated_gain += gain
    for slot in out.values():
        slot["gain"] = round(slot["gain"], 2)
    if exception := out_of_year_exception(records):
        out["out_of_year"] = exception
    if undated:
        out["undated"] = {"window": "no readable date of sale", "rows": undated,
                          "gain": round(undated_gain, 2),
                          "note": "These rows carry no readable date of sale, "
                                  "so they are in no window. Date them from the "
                                  "contract notes before any timing working — "
                                  "s.234C among them. They are gross and "
                                  "pre-set-off like the rest of this split, so "
                                  "they are not Table F input either."}
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
                                      "buy_value": 0.0, "unreadable_gain_rows": 0,
                                      "records": []})
        entry["rows"] += 1
        for f in ("gain", "sell_value", "buy_value"):
            if rec.get(f) is not None:
                entry[f] += rec[f]          # rounded once, at the end
        if b == "dividend" and rec.get("amount") is not None:
            entry["gain"] += rec["amount"]
        elif rec.get("gain") is None:
            entry["unreadable_gain_rows"] += 1
        entry["records"].append(rec)

    for b, entry in list(buckets.items()) + list(needs.items()):
        for f in ("gain", "sell_value", "buy_value"):
            entry[f] = round(entry[f], 2)
        if entry["unreadable_gain_rows"]:
            entry["gain_unreadable_rows"] = entry.pop("unreadable_gain_rows")
            # A partial aggregate is as misleading as a fabricated zero.
            entry.pop("gain")
        else:
            entry.pop("unreadable_gain_rows")
        # Date scope is independent of whether its amount is safe to publish.
        # A withheld bucket still needs to warn when rows predate FY 2025-26.
        if exception := out_of_year_exception(
                entry["records"], amount_is_usable=b not in NON_RUPEE_BUCKETS):
            entry["out_of_year"] = exception
        # The reader never learns a per-row currency, so no foreign aggregate
        # is meaningful in machine-readable output either.
        if b in NON_RUPEE_BUCKETS:
            for f in ("gain", "sell_value", "buy_value"):
                entry.pop(f)

    for b, entry in buckets.items():
        meta = BUCKETS.get(b, {})
        entry["schedule"] = meta.get("schedule", "unclassified")
        entry["label"] = meta.get("label", b)
        if b in SCHEDULE_CG_BUCKETS:
            if withheld := quarterly_withholding_reason(
                    b, entry["records"], entry.get("gain_unreadable_rows", 0)):
                entry["quarterly_withheld"] = withheld
            else:
                entry["quarterly"] = quarterly_split(entry["records"])
                entry["quarterly_basis"] = (DIVIDEND_BASIS if b == "dividend"
                                            else QUARTERLY_BASIS)
        # An unresolved bucket often holds more than one rate category — a
        # non-equity bucket carries both the short-term and the long-term rows —
        # and Schedule CG item F wants them apart. The bucket total answers
        # "how much"; this answers "which window, at which rate".
        sections = sorted({r.get("section") for r in entry["records"]
                           if r.get("section")})
        if (len(sections) > 1 and b not in QUARTERLY_NOT_PUBLISHABLE
                and not grandfathering_unsettled(b, entry["records"])
                and b in UNRESOLVED_CG_BUCKETS):
            entry["quarterly_by_section"] = {
                section: quarterly_split(
                    [r for r in entry["records"] if r.get("section") == section])
                for section in sections}
    for b, entry in needs.items():
        q, why = RESOLVERS[b]
        entry["question"] = q
        entry["why_it_matters"] = why
        # The item F windows are a fact about the dates a disposal happened on,
        # so for a bucket whose question changes only the RATE or the HEAD they
        # can be given straight away — withholding them forces exactly the hand
        # arithmetic this parser exists to prevent.
        #
        # For a bucket whose answer changes the AMOUNT they cannot. A buyback on
        # or after 1 October 2024 turns its whole consideration into a deemed
        # dividend and its capital result into a loss of the entire cost, so the
        # broker's gain is not the figure Schedule CG will carry. Land or
        # building may need the indexed gain. Publishing a quarterly split of a
        # figure that is about to change would produce a confident wrong
        # working, which is worse than none.
        if withheld := quarterly_withholding_reason(
                b, entry["records"], entry.get("gain_unreadable_rows", 0)):
            entry["quarterly_withheld"] = withheld
        else:
            entry["quarterly"] = quarterly_split(entry["records"])
            entry["quarterly_basis"] = QUARTERLY_BASIS
        # An unresolved bucket often holds more than one rate category — a
        # non-equity bucket carries both the short-term and the long-term rows —
        # and Schedule CG item F wants them apart. The bucket total answers
        # "how much"; this answers "which window, at which rate".
        sections = sorted({r.get("section") for r in entry["records"]
                           if r.get("section")})
        if (len(sections) > 1 and not quarterly_withholding_reason(
                    b, entry["records"], entry.get("gain_unreadable_rows", 0))
                and b in UNRESOLVED_CG_BUCKETS):
            entry["quarterly_by_section"] = {
                section: quarterly_split(
                    [r for r in entry["records"] if r.get("section") == section])
                for section in sections}

    checks: list[str] = []
    unvalidated_positions = {
        i for i, st in enumerate(statements)
        if st.source not in VALIDATED_BROKER_LAYOUTS and st.records
    }

    # Generic matching remains deliberate: it lets a new broker layout be
    # inspected without first encoding a positional parser. Refusing all such
    # files would remove that workflow. The result is therefore retained, but
    # the uncertainty lives in the primary safety channel and every total check
    # it affects is worded as a heuristic match rather than verification.
    flags: list[str] = []
    if unvalidated_positions:
        status = []
        for i in sorted(unvalidated_positions):
            st = statements[i]
            if st.source == "unknown":
                status.append(
                    f"{st.file} could not be associated with a recognised "
                    "broker brand, and its layout has not been validated")
            else:
                status.append(
                    f"{st.file} was recognised as {st.source}, but no "
                    f"{st.source} layout has been validated against a real "
                    "specimen")
        flags.append(
            f"UNVERIFIED LAYOUT: {'; '.join(status)}. Values below come from "
            "heuristic "
            "heading and column matches, not a validated broker layout. Do not "
            "put them into Schedule CG until every matched row and omitted "
            "section has been checked against the statement; run --inspect to "
            "record the layout for a fixture-backed parser update.")

    def entry_has_unvalidated(entry: dict) -> bool:
        return any(r.get("_statement") in unvalidated_positions
                   for r in entry["records"])

    if any("quarterly" in e for e in buckets.values()):
        checks.append(
            "Each capital-gains bucket carries a quarterly split, keyed on the "
            "date of sale, before any statutory set-off — and NET within a "
            "window that holds both gains and losses, where `gains` and "
            "`losses` carry the two sides. [documented] Schedule "
            "CG Table F uses the same five windows but wants figures NET of "
            "current-year and brought-forward set-off, each row equal to the "
            "corresponding Schedule BFLA figure, and it rejects negatives — so "
            "fill Table F last, from BFLA, not from these numbers. What these "
            "are for is s.234C, which turns on when the gain arose and which "
            "the portal will not work out for you. Schedule OS wants the same "
            "windows for dividends.")

    if "112A" in buckets:
        gross = buckets["112A"].get("gain")
        unvalidated_112a = entry_has_unvalidated(buckets["112A"])
        if gross is None:
            checks.append(
                "At least one 112A row has no readable gain, so no 112A total "
                "is published. Check the broker's Taxable Profit or Profit "
                "column before applying the 1,25,000 exemption.")
        elif unvalidated_112a:
            checks.append(
                f"Heuristic heading and column matches produced an 112A figure "
                f"of {gross:,.2f}. Because a layout that has not been validated "
                "contributes to "
                "it, this is not a verified total. If the rows are confirmed, "
                "the 1,25,000 exemption is once per PAN for the year, not once "
                "per broker or statement.")
        else:
            checks.append(
                f"112A gains total {gross:,.2f} before the 1,25,000 exemption. "
                "That exemption is once per PAN for the year, not once per "
                "broker or per statement — add every source together before "
                "applying it.")
        if any(r.get("fmv") for r in buckets["112A"]["records"]):
            if unvalidated_112a:
                checks.append(
                    "Heuristic matches include a fair market value column on "
                    "some 112A rows. On a layout that has not been validated, "
                    "that does not "
                    "prove grandfathering was applied or that the matched gain "
                    "is taxable; confirm the columns against the statement.")
            else:
                checks.append(
                    "Some 112A rows carry a fair market value, so the broker has "
                    "already applied 31-Jan-2018 grandfathering and the stated "
                    "gain is the taxable one. Do not recompute the cost.")
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

    losses = [b for b, e in buckets.items() if e.get("gain", 0) < 0]
    if losses:
        loss_prefix = (
            f"Heuristic matches produce a net loss in {', '.join(losses)}; this "
            "is not a verified loss."
            if any(entry_has_unvalidated(buckets[b]) for b in losses)
            else f"Net loss in {', '.join(losses)}."
        )
        checks.append(
            f"{loss_prefix} Carrying a loss forward requires the return to be "
            "filed by the s.139(1) due date (s.80) and Schedules CYLA, BFLA and "
            "CFL to be completed. compute_tax.py refuses on losses rather than "
            "guessing the set-off order.")

    # A bucket whose consideration is short of its row count will understate the
    # full value of consideration on Schedule CG, which is a separate figure from
    # the gain and is checked against AIS.
    for b, entry in buckets.items():
        stated = sum(1 for r in entry["records"] if r.get("sell_value") is not None)
        if b != "dividend" and stated < entry["rows"]:
            if entry_has_unvalidated(entry):
                checks.append(
                    f"Heuristic matches in {b}: {entry['rows'] - stated} of "
                    f"{entry['rows']} matched rows had no sale value. The "
                    "consideration figure is therefore incomplete even before "
                    "the layout is validated against a real specimen and the "
                    "statement.")
            else:
                checks.append(
                    f"{b}: {entry['rows'] - stated} of {entry['rows']} rows stated "
                    "no sale value, so the consideration total is short by those "
                    "rows. Schedule CG asks for full value of consideration "
                    "separately from the gain, and AIS is reconciled against "
                    "consideration.")

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
            if bucket in NON_RUPEE_BUCKETS:
                continue
            entry = buckets.get(bucket) or needs.get(bucket) or {}
            got = entry.get("gain")
            if got is None:
                unread = entry.get("gain_unreadable_rows", 0)
                if unread:
                    flags.append(
                        f"{st.file}: the statement's own summary reports "
                        f"{stated:,.2f} under {bucket}, but {unread} parsed "
                        f"row(s) have no readable gain. This bucket total is "
                        "withheld, not missing; get the statement's gain or "
                        "Taxable Profit value before reconciling it.")
                elif abs(stated) > 0.005:
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
                if st.source not in VALIDATED_BROKER_LAYOUTS:
                    checks.append(
                        f"{st.file}: heuristic row matches and a matched summary "
                        f"label both produce {stated:,.2f} under {bucket}. That "
                        "internal agreement is not validation of the layout.")
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
            if st.source not in VALIDATED_BROKER_LAYOUTS:
                checks.append(
                    f"{st.file}: heuristic view match only — {note} This does "
                    "not validate the layout.")
            else:
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


# A broker Tax P&L names its account holder in the header rows of every sheet:
# client ID, full name and PAN. `strip_identifiers` catches the PAN because a
# PAN has a fixed shape, but a person's name and a broker's client code have no
# shape to match on, so they have to be recognised by their label instead.
#
# [observed 2026-07-31] `--inspect` printed all three verbatim, once per sheet,
# on a real workbook — while the parser's own `checks` output was telling the
# reader that "nothing here reproduces them". `--inspect` is what the refusal
# messages send people to run when a layout is unrecognised, which is the exact
# moment they are most likely to paste the output into a bug report.
# An identity label is a whole cell, and the qualifier may sit on either side:
# `[observed 2026-07-31, one real broker workbook]` "Client ID", "Client Name"
# and "PAN". `[inferred]` A registrar or a second broker may equally write
# "Investor Name", "First Holder Name", "Registered Email ID" or "Name of First
# Holder"; those forms are covered because the cost of matching one label too
# many is a masked value, and the cost of matching one too few is a taxpayer's
# name in a public issue.
_IDENTITY_NOUN = (r"(?:client\s*(?:id|code|name)|customer\s*(?:id|name)|ucc"
                  r"|dp\s*id|demat(?:\s*(?:id|no|number|account))?"
                  r"|folio(?:\s*(?:no|number))?|pan|aadhaar|name"
                  r"|e-?mail(?:\s*id)?|mobile(?:\s*(?:no|number))?"
                  r"|phone(?:\s*(?:no|number))?|address"
                  r"|account\s*(?:holder|name|id|no|number))")
IDENTITY_LABEL = re.compile(
    r"^\s*(?:[A-Za-z&./'’-]+\s+){0,3}"   # Investor / First Holder / Father's
    + _IDENTITY_NOUN +
    r"(?:\s+(?:of|for)\s+(?:[A-Za-z&./'’-]+\s*){1,3})?"  # Name of First Holder
    r"\s*:?\s*$", re.I)

# "Label: value" inside one cell, which no cell split would separate.
IDENTITY_INLINE = re.compile(
    r"^\s*((?:[A-Za-z&./'’-]+\s+){0,3}" + _IDENTITY_NOUN +
    r"(?:\s+(?:of|for)\s+(?:[A-Za-z&./'’-]+\s*){1,3})?)\s*:\s*\S.*$", re.I)


# Words that head a column rather than name a person. Matched whole, because a
# value like "Value Added Services Ltd" is a holding and "Value" is a heading.
COLUMN_WORDS = frozenset("""
    value amount date dates qty quantity quantities price prices rate rates
    total totals units unit isin symbol scrip security type code description
    particulars balance credit debit profit loss gain gains cost proceeds
    consideration charges tax turnover holding period days remarks status
    """.split())


def _looks_like_column_name(text: str) -> bool:
    """Whether a cell reads as a column heading rather than a value."""
    words = re.findall(r"[A-Za-z]+", text)
    if not words or any(ch.isdigit() for ch in text):
        return False
    return all(word.lower() in COLUMN_WORDS for word in words)


def _is_identity_label(text: str) -> bool:
    return bool(IDENTITY_LABEL.match(text))


def safe_sheet_name(name: str) -> str:
    """A worksheet name with any identity it carries removed.

    A workbook may name a sheet after its account holder, and the refusal path
    asks the user to describe an unrecognised layout in a public issue — sheet
    names included. Fixed shapes go first, then the inline "Label: value" form.

    What no rule can catch is a sheet simply *named* after a person, because a
    bare name has no shape and no label. `--inspect` says so rather than
    implying the line is safe."""
    inline = IDENTITY_INLINE.match(name)
    if inline:
        return f"{strip_identifiers(inline.group(1).strip())}: {MASK}"
    if _is_identity_label(name):
        return MASK
    return strip_identifiers(name)


def identity_columns(row: list) -> set:
    """Column indices of a header row that name an identity.

    A workbook may lay metadata out columnar — `Client ID | Client Name | PAN`
    on one row and their values on the next. Read row by row, the label row is
    harmless and the value row looks like data, so the name goes straight to
    stdout. Returns indices only when the row is entirely labels, so a data row
    that happens to open with an identity-shaped cell does not poison the row
    after it."""
    cells = [cell_text(c) for c in non_empty(row)]
    if len(cells) < 2:
        return set()
    if not all(_is_identity_label(c) or _looks_like_column_name(c)
               for c in cells):
        return set()
    return {i for i, c in enumerate(cells) if _is_identity_label(c)}


def safe_row_text(row: list, inherited: set | None = None) -> str:
    """Display text for one row, with any identity it carries removed.

    Two passes, because they catch different things. The fixed-shape sweep
    removes a PAN, TAN, Aadhaar, IFSC or long digit run wherever it sits. The
    label pass removes a value that is only identifiable by what it is called —
    a person's name and a broker's client code have no shape to match on.

    The label pass treats a row as key/value metadata only when **every**
    label-position cell is an identity label. That is what separates
    `Client Name | SPECIMEN | PAN | ABCDE1234F`, where positions 0 and 2 are
    both identity labels, from a table header like `Name | ISIN | Entry Date`,
    where position 2 is not — so an unrecognised compact header such as
    `Name | Date | Value` keeps its columns, which is the whole purpose of this
    mode. A header this cannot classify keeps its structure and loses nothing,
    because a header cell holds a column name and not a person."""
    cells = [cell_text(c) for c in non_empty(row)]
    if not cells:
        return strip_identifiers(row_text(row))
    inherited = inherited or set()

    # One cell carrying "Label: value".
    if len(cells) == 1:
        inline = IDENTITY_INLINE.match(cells[0])
        if inline:
            return f"{strip_identifiers(inline.group(1).strip())}: {MASK}"
        return strip_identifiers(row_text(row))

    # Each cell may carry its own "Label: value".
    rendered = []
    for cell in cells:
        inline = IDENTITY_INLINE.match(cell)
        rendered.append(f"{strip_identifiers(inline.group(1).strip())}: {MASK}"
                        if inline else strip_identifiers(cell))

    # Then key/value pairs. Each identity key masks its **own** value and leaves
    # the rest of the row alone, so `Client Name | X | Status | Active` keeps
    # Status while masking X. A two-column header has the same shape as a pair,
    # so the value side decides: masking a column name would destroy the layout
    # this mode exists to report.
    # Skipped on a row that is entirely labels: that is a columnar header, and
    # its own headings are structure, not values. The row beneath it is where
    # the values live, and `inherited` covers that.
    if not identity_columns(row):
        for index in range(0, len(cells) - 1, 2):
            if (_is_identity_label(cells[index])
                    and not _looks_like_column_name(cells[index + 1])
                    and not IDENTITY_INLINE.match(cells[index])):
                rendered[index + 1] = MASK

    # Columns the row above declared to be identity fields.
    for index in inherited:
        if index < len(rendered) and not _looks_like_column_name(cells[index]):
            rendered[index] = MASK
    return " ".join(rendered)


def inspect(path: str) -> None:
    sheets = load_sheets(path)
    print(f"{safe_name(path)} — {len(sheets)} sheet(s), "
          f"detected source: {detect_source(sheets)}")
    # A sheet or a cell may simply *be* a person's name, which has no shape and
    # no label to match on. Say so rather than letting the masks imply the
    # output has been made safe to publish.
    print("  Identifiers of a known shape and labelled identity values are "
          "masked below. A sheet or\n  value that is only a name cannot be "
          "detected — read before pasting this into an issue.\n")
    for name, rows in sheets.items():
        print(f"  [{safe_sheet_name(name)}] {len(rows)} rows")
        inherited: set = set()
        for i, row in enumerate(rows[:40]):
            cells = non_empty(row)
            if not cells:
                continue
            kind = ""
            if len(cells) == 1:
                kind = f"  <- heading, matched: {match_section(row_text(row))}"
            elif map_header(row) is not None:
                kind = ("  <- header, fields: "
                        f"{sorted(f for f in map_header(row) if not f.startswith('__'))}")
            print(f"    {i:>3}: {safe_row_text(row, inherited)[:100]}{kind}")
            # A columnar label row protects only the row directly beneath it.
            inherited = identity_columns(row)
        if len(rows) > 40:
            print(f"    ... {len(rows) - 40} more rows")
        print()


def summary_lines(result: dict) -> str:
    """The figures a preparer reads first, and every flag, in a few lines."""
    def amount(value, bucket, entry):
        if bucket not in NON_RUPEE_BUCKETS and value is not None:
            return f"₹{value:,.2f}"
        if value is None and bucket not in NON_RUPEE_BUCKETS:
            return "amount not read"
        # Statement identity is not currency identity: a consolidated export
        # can mix USD, GBP and other units, and this parser reads no per-row
        # currency field. Even one statement therefore cannot yield a sum.
        return ("not totalled — this reader does not read currency per row, so "
                "foreign-statement amounts cannot be added")

    lines = ["FY 2025-26 (AY 2026-27) — timing windows below apply only to this year"]

    def timing_lines(bucket, entry):
        def windows(section, quarterly, prefix):
            # "undated" last, and never omitted: it is the amount nobody has
            # placed in a window yet, and leaving it out of the summary lets a
            # reader build an understated s.234C working from what remains.
            for key in [q[0] for q in QUARTERS] + ["undated"]:
                if window := quarterly.get(key):
                    label = (window["window"] if section == "Timing"
                             else f"{section}, {window['window']}")
                    lines.append(
                        f"{prefix}{label}: {amount(window['gain'], bucket, entry)} "
                        f"over {window['rows']} row(s)")
                    if note := window.get("note"):
                        lines.append(f"{prefix.rstrip('— ')}  {note}")

        shown = False
        if quarterly := entry.get("quarterly"):
            windows("Timing", quarterly, "    Timing — ")
            shown = True
        for section, quarterly in (entry.get("quarterly_by_section") or {}).items():
            windows(section, quarterly, "    Timing — ")
            shown = True
        # The qualification travels with the figures, in both groups. Printing
        # a rupee timing window without it changes how the number may be used.
        if shown and (basis := entry.get("quarterly_basis")):
            lines.append(f"    Timing basis: {basis}")

    for src in result.get("sources", []):
        lines.append(f"{src['file']} — detected {src['detected']}, "
                     f"{src['rows_parsed']} row(s) parsed")
    for bucket, entry in (result.get("buckets") or {}).items():
        lines.append(f"  {bucket}: {amount(entry.get('gain'), bucket, entry)} over "
                     f"{entry['rows']} row(s) — {entry.get('schedule', '')}")
        if withheld := entry.get("quarterly_withheld"):
            lines.append(f"    Amount/timing withheld: {withheld}")
        timing_lines(bucket, entry)
    for bucket, entry in (result.get("needs_confirmation") or {}).items():
        lines.append(f"  {bucket}: {amount(entry.get('gain'), bucket, entry)} over "
                     f"{entry['rows']} row(s) — NOT in any total until answered: "
                     f"{entry.get('question', '')}")
        # A question the reader cannot act on is the unreachable-guidance defect
        # one step along. Where the answer is written down, summary mode has to
        # carry the pointer too — it is the mode a preparer reads.
        for sentence in (entry.get("why_it_matters") or "").split(". "):
            if "references/" in sentence:
                text = sentence.strip().rstrip(".")
                lines.append(f"    See {text[4:] if text.startswith('See ') else text}.")
        if withheld := entry.get("quarterly_withheld"):
            lines.append(f"    Amount/timing withheld: {withheld}")
        timing_lines(bucket, entry)
    out_of_year = []
    for group_name, group in (("buckets", result.get("buckets") or {}),
                              ("needs confirmation",
                               result.get("needs_confirmation") or {})):
        for bucket, entry in group.items():
            quarterly = entry.get("quarterly") or {}
            exception = entry.get("out_of_year") or quarterly.get("out_of_year")
            if exception:
                out_of_year.append((group_name, bucket, entry, exception))
    if out_of_year:
        lines.append("\nOut-of-year rows")
        for group_name, bucket, entry, exception in out_of_year:
            scope = ("the exception amount was not read"
                     if exception.get("amount_unreadable_rows") else
                     "it remains in the bucket's raw figure")
            lines.append(
                f"{bucket} ({group_name}): {exception['rows']} row(s), "
                f"{amount(exception.get('gain'), bucket, entry)}, dated outside "
                f"FY 2025-26 — {scope} but is "
                "outside the FY timing scope. Check which year the file covers "
                "before using it.")
    warned = sorted({flag for entry in
                     list((result.get("buckets") or {}).values())
                     + list((result.get("needs_confirmation") or {}).values())
                     for flag in (entry.get("row_flags") or [])})
    if warned:
        # The tally elsewhere truncates these at the first semicolon; the
        # summary prints totals without samples, so the unabridged sentence is
        # the only place a reader learns transfer costs were not deducted.
        lines.append("\nRow warnings")
        lines += [str(w) for w in warned]
    if result.get("refused"):
        lines.append(f"\nRefused\n{result['refused']}")
    for key, heading in (("flags", "Flags"), ("checks", "Checks")):
        values = result.get(key) or []
        if values:
            lines.append(f"\n{heading}")
            lines += [str(v) for v in values]
    # The abbreviated mode must not abbreviate the qualification on the figures
    # it prints. It is the easiest output to read and so the likeliest to be
    # acted on directly.
    if result.get("disclaimer"):
        lines.append(f"\n{result['disclaimer']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help=".xlsx or .csv statements")
    ap.add_argument("--json", metavar="PATH", help="write the full result to a file")
    ap.add_argument("--inspect", action="store_true",
                    help="print the sheet structure instead of parsing — use this "
                         "when a broker layout is not recognised")
    ap.add_argument("--summary", action="store_true",
                    help="a few lines instead of the full JSON")
    ap.add_argument("--rows", action="store_true", help="include every parsed row in stdout")
    a = ap.parse_args(argv)

    conflicting = [name for name, on in
                   (("--inspect", a.inspect), ("--rows", a.rows)) if on]
    if a.summary and conflicting:
        print(json.dumps({"refused":
            f"--summary and {', '.join(conflicting)} ask for two different "
            "stdout modes. --summary prints a few lines, --inspect prints the "
            "sheet structure without parsing, and --rows prints every parsed "
            "row. Pick one, or use --json to write the full detail to a file "
            "alongside --summary."}, indent=2), file=sys.stderr)
        return 2

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
            # --summary promises a few lines instead of the full JSON, and a
            # malformed, encrypted, unsupported or PDF input is exactly when a
            # reader wants the sentence rather than the object.
            if a.summary:
                print(f"Refused\n{e}", file=sys.stderr)
            else:
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
        # --summary promises a few lines instead of the full JSON, and an
        # unrecognised layout is the commonest time a reader wants them.
        if a.summary:
            print(summary_lines(result), file=sys.stderr)
        else:
            print(json.dumps(result, indent=2), file=sys.stderr)
        return 2

    # Before truncating: a caveat on the fourth row is as important as one on
    # the first, and the sample keeps only three.
    for entry in (list(result["buckets"].values())
                  + list(result["needs_confirmation"].values())):
        flags = sorted({flag for row in entry["records"]
                        if isinstance(row, dict)
                        for flag in (row.get("flags") or [])})
        if flags:
            entry["row_flags"] = flags
        # Counted here for the same reason: the sample keeps three rows, and a
        # second statement's rows may all sit past them.
        # By statement index, not by name: safe_name() reduces a path to its
        # basename, so a/report.csv and b/report.csv would count as one.
        entry["source_files"] = len({row.get("_statement")
                                     for row in entry["records"]
                                     if isinstance(row, dict)
                                     and row.get("_statement") is not None})

    if not a.rows:
        for entry in list(result["buckets"].values()) + list(result["needs_confirmation"].values()):
            entry["sample"] = entry["records"][:3]
            entry["records"] = f"{len(entry['records'])} rows — pass --rows or --json to see them"

    if a.summary:
        print(summary_lines(result))
    else:
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
