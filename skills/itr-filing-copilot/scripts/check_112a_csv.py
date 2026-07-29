#!/usr/bin/env python3
"""
Check a Schedule 112A CSV before you upload it.

Standard library only. Reads the file you name and nothing else. No network.

    python3 check_112a_csv.py schedule112a.csv
    python3 check_112a_csv.py schedule112a.csv --template fresh_template.csv

The portal rejects this file in three ways, each with an error message that
names nothing useful:

  "Please import the details in correct template"
      The header line is wrong. The official header contains non-breaking
      spaces (U+00A0), and its quoting differs between downloads. Retyping it,
      reusing last year's, or opening the file in Excel and saving it all
      produce a header that looks identical and is rejected.

  "common.errors.csv_row_skip"
      Every row was dropped. A derived column disagrees with its formula, a
      name contains a character the portal forbids, an amount carries paise,
      or a dropdown label was pasted in place of BE or AE.

  A silent partial import
      Rows the portal could not read are skipped without comment, so the total
      is quietly short.

This script finds all three before the upload, and prints the row and column
for each. Pass --template with a freshly downloaded template to compare the
header byte for byte, which is the only way to be certain about the first one.

The procedure that imports first try
------------------------------------
1. Build the data rows to the column rules below, in any tool.
2. Download a FRESH template from the portal immediately before uploading.
3. In a plain-text editor, not Excel, paste only your data rows underneath the
   template's own header line, leaving that line untouched. Save.
4. Run this script on the result, then upload.

Column rules
------------
  1a  BE if acquired on or before 31-Jan-2018, AE if after
  1b  BE or AE, for the transfer
  2   ISIN, starts IN. No ISIN: INNOTAVAILAB. If 1a is AE: INNOTREQUIRD
  3   Name, alphanumeric only. If 1a is AE: CONSOLIDATED
  4   Units. Blank if AE
  5   Sale price per unit. Blank if AE
  6   Full value of consideration. If BE: round(4 x 5). If AE: entered directly
  7   Cost without indexation: the HIGHER of columns 8 and 9
  8   Cost of acquisition
  9   BE only: the LOWER of columns 11 and 6
  10  FMV per unit on 31-Jan-2018. Blank if AE
  11  Total FMV u/s 55(2)(ac): round(4 x 10)
  12  Transfer expenditure
  13  Total deductions: 7 + 12
  14  Balance: 6 - 13

Consolidate every post-2018 lot into one AE row. Enter BE lots per scrip with
their 31-Jan-2018 fair market value. Whole rupees throughout.

Sources: the portal's own "Need Help → 112A/115AD CSV Instructions", the
column list as it appears in a downloaded AY 2026-27 template, and a live
33-row upload. Re-check against a fresh template each assessment year — the
portal is re-released every May or June and column text has moved before.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from decimal import Decimal, ROUND_HALF_UP

COLUMNS = (
    "Share/Unit acquired(1a)",
    "Share/Unit Transferred(1b)",
    "ISIN Code(2)",
    "Name of the Share/Unit(3)",
    "No. of Shares/Units(4)",
    "Sale-price per Share/Unit(5)",
    "Full Value of Consideration(Total Sale Value)(6) = 4 * 5",
    "Cost of acquisition without indexation(7)",
    "Cost of acquisition(8)",
    "If the long term capital asset was acquired before 01.02.2018(9)",
    "Fair Market Value per share/unit as on 31st January 2018(10)",
    "Total Fair Market Value of capital asset as per section 55(2)(ac)(11) = 4 * 10",
    "Expenditure wholly and exclusively in connection with transfer(12)",
    "Total deductions(13) = 7 + 12",
    "Balance(14) = 6 - 13",
)
IDX = {name: i for i, name in enumerate(COLUMNS)}
NBSP = " "

# The portal accepts alphanumerics and spaces in the text columns. Checking the
# numeric columns for the same set would flag the minus sign on a capital loss.
ALLOWED_TEXT = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ")
ISIN_RE = re.compile(r"^IN[0-9A-Z]{10}$")
SENTINELS = {"INNOTAVAILAB", "INNOTREQUIRD"}
LTCG_112A_EXEMPT = Decimal(125000)


def read_text(path: str) -> tuple[str, str]:
    """Read a CSV that may be UTF-8, UTF-8 with a BOM, or the cp1252 a
    spreadsheet application writes. Decoding strictly as UTF-8 crashes on the
    non-breaking spaces in an Excel-saved header, which is precisely the file
    this script exists to diagnose."""
    data = open(path, "rb").read()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "unknown"


class Finding:
    __slots__ = ("severity", "row", "column", "message", "fix")

    def __init__(self, severity, message, row=None, column=None, fix=None):
        self.severity, self.message = severity, message
        self.row, self.column, self.fix = row, column, fix

    def as_dict(self):
        d = {"severity": self.severity, "message": self.message}
        if self.row is not None:
            d["row"] = self.row
        if self.column:
            d["column"] = self.column
        if self.fix:
            d["fix"] = self.fix
        return d

    def __str__(self):
        where = ""
        if self.row is not None:
            where = f"row {self.row}" + (f", col {self.column}" if self.column else "")
            where = f"[{where}] "
        out = f"{self.severity:<8} {where}{self.message}"
        return out + (f"\n         fix: {self.fix}" if self.fix else "")


def portal_col(index: int) -> str:
    """The portal numbers columns 1a, 1b, 2, 3 ... 14, so a zero-based index is
    the portal's own number from 2 onward. Reporting index+1 sent people to the
    wrong column, and to a column 15 that does not exist."""
    return ("1a", "1b")[index] if index < 2 else str(index)


def norm(text: str) -> str:
    """Header text with whitespace differences flattened, for comparison."""
    return re.sub(r"\s+", " ", (text or "").replace(NBSP, " ")
               .replace("\ufeff", "")).strip().lower()


def dec(value: str):
    s = (value or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except Exception:
        return None


def r0(value: Decimal) -> Decimal:
    return value.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def check_header(raw_line: str, template_line: str | None, out: list[Finding]) -> list[str] | None:
    """Validate the header line. Returns the parsed header, or None if unusable."""
    header = next(csv.reader(io.StringIO(raw_line)))
    header = [h.strip() for h in header]

    if template_line is not None:
        if raw_line.rstrip("\r\n") == template_line.rstrip("\r\n"):
            out.append(Finding("ok", "Header matches the supplied template byte for byte."))
        else:
            out.append(Finding("BLOCKER",
                "Header does not match the supplied template byte for byte. This is "
                "the cause of \"Please import the details in correct template\".",
                fix="Open the fresh template in a plain-text editor, paste only your "
                    "data rows below its header, and save. Do not edit the header, "
                    "and do not open the file in Excel afterwards."))
            if norm(raw_line) == norm(template_line):
                out.append(Finding("info",
                    "The two headers differ only in whitespace or quoting, which is "
                    "exactly the failure mode: the template's non-breaking spaces or "
                    "quoting were changed, most often by a spreadsheet round trip."))

    if len(header) != len(COLUMNS):
        out.append(Finding("BLOCKER",
            f"Header has {len(header)} columns; the template has {len(COLUMNS)}.",
            fix="Use an unmodified template header."))
        return header if len(header) >= len(COLUMNS) else None

    for i, (got, want) in enumerate(zip(header, COLUMNS)):
        if norm(got) != norm(want):
            out.append(Finding("BLOCKER",
                f"Column {portal_col(i)} reads {got!r}; the template has {want!r}.",
                column=portal_col(i),
                fix="Re-download the template. Column text changes between assessment "
                    "years, so a header kept from last year will be rejected."))

    if template_line is None:
        if NBSP not in raw_line:
            out.append(Finding("warn",
                "No non-breaking space anywhere in the header. Official templates "
                "contain them, so this header was probably retyped or saved by a "
                "spreadsheet application, and the portal will reject it.",
                fix="Download a fresh template and paste your data rows under its "
                    "header in a plain-text editor. Pass --template to check for certain."))
        else:
            out.append(Finding("info",
                "Header carries non-breaking spaces, which is a good sign, but only "
                "--template with a freshly downloaded file proves it byte for byte."))
    return header


def check_row(n: int, row: list[str], out: list[Finding]) -> Decimal | None:
    """Validate one data row. Returns column 14 where it can be read."""
    def col(name):
        i = IDX[name]
        return row[i].strip() if i < len(row) else ""

    if len(row) != len(COLUMNS):
        out.append(Finding("BLOCKER",
            f"Row has {len(row)} fields, expected {len(COLUMNS)}. The whole row is skipped.",
            row=n, fix="Check for a stray comma inside a name, or a missing trailing field."))
        return None

    for i, value in enumerate(row[:4]):
        bad = sorted(c for c in set(value) if c not in ALLOWED_TEXT)
        if bad:
            out.append(Finding("BLOCKER",
                f"Contains forbidden character(s) {' '.join(bad)} in {value!r}.",
                row=n, column=portal_col(i),
                fix="Data rows accept alphanumerics and spaces only. A hyphen in a "
                    "scrip name is the usual culprit — remove it, do not replace it."))

    acquired, transferred = col(COLUMNS[0]).upper(), col(COLUMNS[1]).upper()
    for label, value in (("1a", acquired), ("1b", transferred)):
        if value not in ("BE", "AE"):
            out.append(Finding("BLOCKER",
                f"Column {label} is {value!r}; it must be exactly BE or AE.",
                row=n, column=label,
                fix="Pasting the dropdown's full wording instead of the two-letter "
                    "code skips every row in the file."))

    isin, name = col(COLUMNS[2]).upper(), col(COLUMNS[3])
    if acquired == "AE":
        if isin != "INNOTREQUIRD":
            out.append(Finding("BLOCKER",
                f"1a is AE so the ISIN must read INNOTREQUIRD, not {isin!r}.",
                row=n, column="2"))
        if name.upper() != "CONSOLIDATED":
            out.append(Finding("BLOCKER",
                f"1a is AE so the name must read CONSOLIDATED, not {name!r}.",
                row=n, column="3"))
        for label, cname in (("4", COLUMNS[4]), ("5", COLUMNS[5]), ("9", COLUMNS[9]),
                             ("10", COLUMNS[10]), ("11", COLUMNS[11])):
            if col(cname):
                out.append(Finding("BLOCKER",
                    f"1a is AE so column {label} must be blank; it holds {col(cname)!r}.",
                    row=n, column=label))
    else:
        if isin not in SENTINELS and not ISIN_RE.match(isin):
            out.append(Finding("BLOCKER",
                f"ISIN {isin!r} is not 12 characters starting IN.",
                row=n, column="2",
                fix="Where the security has no ISIN, write INNOTAVAILAB."))

    values = {}
    for label, cname in (("4", COLUMNS[4]), ("5", COLUMNS[5]), ("6", COLUMNS[6]),
                         ("7", COLUMNS[7]), ("8", COLUMNS[8]), ("9", COLUMNS[9]),
                         ("10", COLUMNS[10]), ("11", COLUMNS[11]), ("12", COLUMNS[12]),
                         ("13", COLUMNS[13]), ("14", COLUMNS[14])):
        raw = col(cname)
        if raw == "":
            values[label] = None
            continue
        v = dec(raw)
        if v is None:
            out.append(Finding("BLOCKER", f"Column {label} is not a number: {raw!r}.",
                               row=n, column=label))
        values[label] = v

    required = ["6", "7", "8", "12", "13", "14"]
    if acquired == "BE":
        required += ["4", "5", "9", "10", "11"]
    for label in required:
        if values.get(label) is None:
            out.append(Finding("BLOCKER",
                f"Column {label} is blank. It is required on a "
                f"{acquired or 'data'} row, and a blank here drops the row from "
                f"the portal's total without saying so.",
                row=n, column=label))

    def eq(label, expected, rule):
        got = values.get(label)
        if got is None or expected is None:
            return
        if got != expected:
            out.append(Finding("BLOCKER",
                f"Column {label} is {got}, but {rule} gives {expected}.",
                row=n, column=label,
                fix="The portal recomputes every derived column and skips the row "
                    "when its own answer differs."))

    if acquired == "BE" and values.get("4") is not None and values.get("5") is not None:
        eq("6", r0(values["4"] * values["5"]), "round(col4 x col5)")
    if acquired == "BE" and values.get("4") is not None and values.get("10") is not None:
        eq("11", r0(values["4"] * values["10"]), "round(col4 x col10)")
    if acquired == "BE" and values.get("11") is not None and values.get("6") is not None:
        eq("9", min(values["11"], values["6"]), "the lower of col11 and col6")
    if values.get("8") is not None:
        if acquired == "BE" and values.get("9") is not None:
            eq("7", max(values["8"], values["9"]), "the higher of col8 and col9")
        else:
            # Column 9 exists only for shares acquired before 01-02-2018. Letting
            # it into the comparison on an AE row inflates the cost and hides gain.
            eq("7", values["8"], "col8, since col9 applies only to BE rows")
    if values.get("7") is not None and values.get("12") is not None:
        eq("13", values["7"] + values["12"], "col7 + col12")
    if values.get("6") is not None and values.get("13") is not None:
        eq("14", values["6"] - values["13"], "col6 - col13")

    for label in ("6", "7", "8", "9", "11", "12", "13", "14"):
        v = values.get(label)
        if v is not None and v != v.to_integral_value():
            out.append(Finding("warn",
                f"Column {label} carries paise ({v}). Amounts should be whole rupees.",
                row=n, column=label,
                fix="Round before uploading. The portal re-floors these on import, "
                    "so its displayed total will differ from your file."))
    return values.get("14")


def run(path: str, template: str | None) -> dict:
    out: list[Finding] = []
    raw, encoding = read_text(path)
    if encoding != "utf-8-sig":
        out.append(Finding("warn",
            f"File is {encoding}, not UTF-8. A spreadsheet application wrote it, "
            "which is the exact path that damages the template header.",
            fix="Rebuild it in a plain-text editor from a fresh template."))
    if not raw.strip():
        return {"findings": [Finding("BLOCKER", "File is empty.").as_dict()],
                "ok": False, "rows": 0}

    lines = raw.splitlines(keepends=True)
    template_line = None
    if template:
        template_line = read_text(template)[0].splitlines(keepends=True)[0]

    header = check_header(lines[0], template_line, out)
    if header is None:
        return {"findings": [f.as_dict() for f in out], "ok": False, "rows": 0}

    numbered = [(i, r) for i, r in
                enumerate(csv.reader(io.StringIO("".join(lines[1:]))), start=2)
                if any(cell.strip() for cell in r)]
    rows = [r for _, r in numbered]

    total = Decimal(0)
    ae_rows = 0
    for i, row in numbered:
        if (row[0] or "").strip().upper() == "AE":
            ae_rows += 1
        balance = check_row(i, row, out)
        if balance is not None:
            total += balance

    if not rows:
        out.append(Finding("BLOCKER", "No data rows below the header."))
    if ae_rows > 1:
        out.append(Finding("warn",
            f"{ae_rows} separate AE rows. Every lot acquired after 31-Jan-2018 "
            "should be consolidated into a single AE row.",
            fix="Sum them into one row. With exactly one AE row and nothing else, "
                "skip the CSV entirely and use [+ Add] on the schedule."))

    blockers = sum(1 for f in out if f.severity == "BLOCKER")
    summary = {
        "file": path,
        "rows": len(rows),
        "column_14_total": str(total),
        "ok": blockers == 0,
        "blockers": blockers,
        "warnings": sum(1 for f in out if f.severity == "warn"),
        "findings": [f.as_dict() for f in out],
    }
    if total > 0:
        summary["note_112a_exemption"] = (
            f"Column 14 totals {total:,}. The first 1,25,000 of 112A gains is exempt "
            "for the year across every source, not per statement or per broker. "
            f"Taxable at 12.5% on this file alone: "
            f"{max(Decimal(0), total - LTCG_112A_EXEMPT):,}. Add gains from any other "
            "broker or registrar before relying on that.")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_file", help="the filled Schedule 112A CSV")
    ap.add_argument("--template", help="a freshly downloaded, unmodified template, "
                                       "for a byte-for-byte header comparison")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    result = run(a.csv_file, a.template)

    if a.json:
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    print(f"{result['file']}: {result['rows']} data row(s)\n")
    for entry in result["findings"]:
        f = Finding(entry["severity"], entry["message"], entry.get("row"),
                    entry.get("column"), entry.get("fix"))
        print(f)
    print()
    if result["ok"]:
        print(f"No blockers. Column 14 totals {result['column_14_total']}.")
        if "note_112a_exemption" in result:
            print("\n" + result["note_112a_exemption"])
        print("\nUpload only a file whose header came from a template downloaded "
              "in this session, and do not open it in Excel first.")
    else:
        print(f"{result['blockers']} blocker(s). The portal will reject this file "
              "or skip rows silently.")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
