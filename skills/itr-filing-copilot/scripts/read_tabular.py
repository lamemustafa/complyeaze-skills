#!/usr/bin/env python3
"""
Minimal XLSX / CSV reader. Standard library only.

Broker tax reports arrive as .xlsx, and the obvious answer is openpyxl. This
module exists so the skill's scripts stay installable with nothing but Python:
a taxpayer following a walkthrough should not have to debug a pip install
before they can read their own capital gains.

An .xlsx is a zip of XML. Reading one is a hundred lines. Writing one is not,
so this only reads.

    from read_tabular import load_sheets
    sheets = load_sheets("tax_pnl.xlsx")     # {sheet name: [[cell, ...], ...]}

Cells come back as str, float, int, or None. Dates come back as ISO strings
where the cell carries a date format, and as floats where it does not — Excel
stores both as serial numbers and only the format tells them apart.
"""
from __future__ import annotations

import csv
import datetime as _dt
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from redact import safe_name  # noqa: E402

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/package/2006/relationships",
}

# Built-in numFmtIds that mean "this is a date or a time". Anything outside
# this set with a custom format is decided by looking at the format string.
BUILTIN_DATE_FMTS = set(range(14, 23)) | set(range(45, 48)) | {27, 30, 36, 50, 57}
DATE_CHARS = re.compile(r"[dmyhs]", re.I)
NOT_DATE = re.compile(r'\[[^\]]*\]|"[^"]*"|\\.')

EXCEL_EPOCH = _dt.date(1899, 12, 30)   # Excel's day 1 is 1900-01-01, off by one

# Placed where a formula cell carries no cached result. Callers should treat it
# as missing and say so, rather than reading it as zero.
UNCACHED_FORMULA = "<formula not calculated>"


class SpreadsheetError(Exception):
    """The file is not a readable spreadsheet."""


def _col_index(ref: str) -> int:
    """'BC12' -> 54 (zero-based column)."""
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _serial_to_iso(value: float):
    """Excel serial date -> ISO string, or the number back when it cannot be one.

    A money column that inherited a date format is common in broker exports, and
    a large amount is not a date. Returning the number is better than crashing,
    and callers can tell the difference because one is a str."""
    try:
        days = int(value)
        frac = value - days
        d = EXCEL_EPOCH + _dt.timedelta(days=days)
        if frac <= 0:
            return d.isoformat()
        secs = round(frac * 86400)
        return (_dt.datetime.combine(d, _dt.time())
                + _dt.timedelta(seconds=secs)).isoformat(" ")
    except (OverflowError, OSError, ValueError):
        return value


def _date_styles(zf: zipfile.ZipFile) -> set[int]:
    """Style indices whose number format is a date or time."""
    try:
        root = ET.fromstring(zf.read("xl/styles.xml"))
    except KeyError:
        return set()
    custom = {}
    for fmt in root.iter(f"{{{NS['m']}}}numFmt"):
        code = fmt.get("formatCode") or ""
        fid = int(fmt.get("numFmtId", "0"))
        custom[fid] = bool(DATE_CHARS.search(NOT_DATE.sub("", code)))
    out = set()
    cell_xfs = root.find("m:cellXfs", NS)
    if cell_xfs is None:
        return out
    for i, xf in enumerate(cell_xfs.findall("m:xf", NS)):
        fid = int(xf.get("numFmtId", "0"))
        if fid in BUILTIN_DATE_FMTS or custom.get(fid):
            out.add(i)
    return out


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out = []
    for si in root.findall("m:si", NS):
        # Rich text splits one string across several <r><t> runs. <rPh> holds
        # phonetic guides, which are not part of the string.
        parts = [t.text or "" for t in si.findall("m:t", NS)]
        for r in si.findall("m:r", NS):
            parts += [t.text or "" for t in r.findall("m:t", NS)]
        out.append("".join(parts))
    return out


def _sheet_paths(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """[(sheet name, zip path)] in workbook order."""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    target = {}
    for rel in rels:
        rid = rel.get("Id")
        tgt = rel.get("Target", "")
        if tgt.startswith("/"):
            tgt = tgt[1:]
        elif not tgt.startswith("xl/"):
            tgt = "xl/" + tgt
        target[rid] = tgt
    out = []
    for sheet in wb.iter(f"{{{NS['m']}}}sheet"):
        rid = sheet.get(f"{{{NS['r']}}}id")
        if rid in target:
            out.append((sheet.get("name", ""), target[rid]))
    return out


def _read_sheet(zf: zipfile.ZipFile, path: str, strings: list[str],
                date_styles: set[int]) -> list[list]:
    root = ET.fromstring(zf.read(path))
    rows: list[list] = []
    for row in root.iter(f"{{{NS['m']}}}row"):
        cells: list = []

        def place(i, value):
            while len(cells) <= i:
                cells.append(None)
            cells[i] = value

        cursor = 0
        for c in row.findall("m:c", NS):
            idx = _col_index(c.get("r", "")) if c.get("r") else cursor
            if idx < 0:
                idx = cursor
            cursor = idx + 1
            ctype = c.get("t", "n")
            if ctype == "inlineStr":
                is_el = c.find("m:is", NS)
                text = "".join(t.text or "" for t in is_el.iter(f"{{{NS['m']}}}t")) \
                    if is_el is not None else None
                place(idx, text)
                continue
            v = c.find("m:v", NS)
            raw = v.text if v is not None else None
            if raw is None:
                # A formula whose result was never cached reads as empty. Saying
                # so beats a silent None in a money column.
                place(idx, UNCACHED_FORMULA if c.find("m:f", NS) is not None else None)
            elif ctype == "s":
                i = int(raw)
                place(idx, strings[i] if 0 <= i < len(strings) else None)
            elif ctype in ("str", "e"):
                place(idx, raw)
            elif ctype == "b":
                place(idx, raw == "1")
            else:
                try:
                    num = float(raw)
                except ValueError:
                    place(idx, raw)
                    continue
                style = int(c.get("s", "0") or 0)
                if style in date_styles and 0 < num < 2958466:
                    place(idx, _serial_to_iso(num))
                elif num == int(num) and abs(num) < 1e15:
                    place(idx, int(num))
                else:
                    place(idx, num)
        rows.append(cells)
    return rows


def load_xlsx(path: str) -> dict[str, list[list]]:
    try:
        with zipfile.ZipFile(path) as zf:
            strings = _shared_strings(zf)
            styles = _date_styles(zf)
            return {name: _read_sheet(zf, p, strings, styles)
                    for name, p in _sheet_paths(zf)}
    except zipfile.BadZipFile:
        # Name what the file actually is before saying what it is not. A broker
        # Tax P&L arrives as a PDF at least as often as a workbook, and telling
        # its owner to re-save a PDF as .xlsx in a spreadsheet application is
        # advice that cannot be followed.
        with open(path, "rb") as fh:
            head = fh.read(5)
        if head.startswith(b"%PDF"):
            raise SpreadsheetError(
                f"{safe_name(path)} is a PDF. [observed] This reader takes "
                "workbooks and CSV only, so a broker Tax P&L has to be the "
                ".xlsx or .csv download rather than the printable one. "
                "[observed] 2026-07-31, one Zerodha Console session: that "
                "download sat under Reports, Tax P&L, beside the PDF button; "
                "[UNVERIFIED] a broker's menu changes without notice and no "
                "other broker's path has been checked. [inferred] Converting "
                "the PDF is not a route worth trying: its tables are drawn "
                "rather than stored, so a converter has to re-derive them and "
                "may do it wrongly without saying so.")
        raise SpreadsheetError(
            f"{safe_name(path)} is not a valid .xlsx. If it is an old .xls "
            "(a different, binary format) or an encrypted workbook, open it in a "
            "spreadsheet application and re-save as .xlsx or .csv.")
    except KeyError as e:
        raise SpreadsheetError(f"{safe_name(path)} is missing {e} — "
                               "not a spreadsheet this reader understands.")


def load_csv(path: str) -> dict[str, list[list]]:
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [[_coerce(cell) for cell in row] for row in csv.reader(fh, dialect)]
    return {safe_name(path): rows}


# Indian grouping (12,34,567.89) and western grouping (1,234,567.89). Anything
# else keeps its commas and stays a string, so a European decimal comma is never
# read as a thousands separator and multiplied by a hundred.
# Both patterns require the final group to be three digits, which is what makes
# "1,23,456" a number and "1,50" a European decimal that must stay a string
# rather than becoming 150.
GROUPED = re.compile(r"^-?\d{1,3}(?:,\d{2})*,\d{3}(?:\.\d+)?$|"
                     r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")


def _coerce(cell: str):
    s = (cell or "").strip()
    if not s:
        return None
    body = s.replace("₹", "").replace("Rs.", "").strip()
    if "," in body:
        if not GROUPED.match(body):
            return s
        body = body.replace(",", "")
    # A leading zero means an identifier — a folio, a client code — not a number.
    if re.fullmatch(r"-?0\d+", body):
        return s
    if re.fullmatch(r"-?\d+", body):
        return int(body)
    if re.fullmatch(r"-?\d*\.\d+", body):
        return float(body)
    return s


def load_sheets(path: str) -> dict[str, list[list]]:
    """Load a workbook or a CSV as {sheet name: rows}."""
    if not os.path.exists(path):
        raise SpreadsheetError(f"no such file: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".txt", ".tsv"):
        return load_csv(path)
    if ext == ".xls":
        raise SpreadsheetError(
            ".xls is the old binary Excel format and this reader only handles "
            ".xlsx. Open it and re-save as .xlsx or CSV. Several brokers still "
            "hand out .xls even when the download is labelled Excel.")
    return load_xlsx(path)


def cell_text(cell) -> str:
    return "" if cell is None else str(cell).strip()


def row_text(row: list) -> str:
    return " ".join(cell_text(c) for c in row).strip()


def non_empty(row: list) -> list:
    return [c for c in row if cell_text(c)]


if __name__ == "__main__":
    import json, sys
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    sheets = load_sheets(sys.argv[1])
    print(json.dumps({name: {"rows": len(rows),
                             "first_rows": [[cell_text(c) for c in r] for r in rows[:5]]}
                      for name, rows in sheets.items()}, indent=2))
