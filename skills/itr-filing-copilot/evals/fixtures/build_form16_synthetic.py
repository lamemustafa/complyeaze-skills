#!/usr/bin/env python3
"""
Rebuild the synthetic employer Form 16 fixture. Standard library only.

    python3 build_form16_synthetic.py

The layout is copied from a real AY 2026-27 employer-issued certificate. The
content is invented: the TAN, the receipt numbers and every figure are
placeholders, and no name, PAN or account number appears anywhere.

What the fixture is for
-----------------------
Three things a real certificate did that the parser could not survive, all of
which cost a full return's worth of hand transcription when they were found.

**It is headed "Form 16", not "FORM NO. 16".** The notified form carries the
"No.", payroll vendors drop it, and a detector requiring it reports the whole
nine-page certificate as UNKNOWN with an empty `data` block. The fixture is
titled the way the real one was.

**The Part B marker is not on the cover sheet.** It sat nine pages in, past
anything a first-4000-characters probe can see, so the cover page here is padded
past that boundary on purpose. Shortening the padding stops the fixture testing
what it exists to test.

**The regime line is the whole point of Part B and it is easy to lose.** The
line reads "Whether opting out of taxation u/s 115BAC(1A)?" and its Yes/No
decides which regime the employer computed on. It is written here in the mixed
case a real certificate uses, so a pattern that is matched case-sensitively
against a lowercased line fails on it.

The certificate also prints its assessment year as "2026-2027". A period pattern
that stops two digits in reports that as "2026-20", which is not a financial
year, not an assessment year, and not flagged as unread.
"""
import sys

TAN = "AAAA00000A"          # already an allowed placeholder; see .github/scripts/scan_pii.py
AY_LONG = "2026-2027"

# Part A — the quarterly statement. The four amounts add to the Part B gross
# salary on purpose: that identity is the cross-check the certificate exists to
# support, and a fixture whose halves do not tie cannot catch a parser that
# reads one of them wrong.
QUARTERS = [
    ("Q1", "AAAAAAAA", "2,21,400.00", "0.00", "0.00"),
    ("Q2", "BBBBBBBB", "1,53,200.00", "0.00", "0.00"),
    ("Q3", "CCCCCCCC", "1,53,200.00", "0.00", "0.00"),
    ("Q4", "DDDDDDDD", "1,61,500.00", "0.00", "0.00"),
]

GROSS_17_1 = "684100.00"
PERQUISITES_17_2 = "5200.00"
GROSS_SALARY = "689300.00"
STANDARD_DEDUCTION = "75000.00"
GROSS_TOTAL_INCOME = "614300.00"
TAX_ON_TOTAL_INCOME = "10715.00"
REBATE_87A = "10715.00"


def cover_page() -> list[str]:
    """Page 1. Titled the way a payroll vendor prints it, and long enough that
    the Part B marker falls outside any first-4000-characters window."""
    out = [
        "SPECIMEN EMPLOYER PRIVATE LIMITED",
        "Form 16",
        "Form 16 Details :                         Digitally Signed",
        "Certificate No. AAAAAAA",
        f"Assessment Year {AY_LONG}",
        f"TAN of Deductor {TAN}",
        "Certificate under Section 203 of the Income-tax Act, 1961 for tax "
        "deducted at source on salary paid to an employee under section 192 "
        "or pension/interest income of specified senior citizen.",
    ]
    # Padding that looks like the standard-form boilerplate a real certificate
    # carries between the header and Part B. Its only job is length.
    for n in range(1, 61):
        out.append(
            f"Note {n}: This certificate is issued in accordance with the "
            "provisions of rule 31 of the Income-tax Rules, 1962 and is valid "
            "subject to verification of the deposit of tax with the Central "
            "Government through the departmental portal."
        )
    return out


def part_a() -> list[str]:
    out = [
        "PART A",
        "Summary of amount paid/credited and tax deducted at source thereon "
        "in respect of the employee",
        # The decoy comes first on purpose. "2026-2027" is printed on the cover
        # sheet, pages ahead of the real financial year, so a period reader that
        # takes the first year-shaped run of digits reports "2026-20" and stops
        # before ever seeing this line.
        "Period with the Employer From 01-Apr-2025 To 31-Mar-2026",
        "Financial Year 2025-26",
        "Quarter(s) Receipt Numbers of original quarterly statements of TDS "
        "Amount paid/credited Amount of tax deducted (Rs.) Amount of tax "
        "deposited/remitted (Rs.)",
    ]
    for quarter, receipt, paid, deducted, deposited in QUARTERS:
        out.append(f"{quarter} {receipt} {paid} {deducted} {deposited}")
    out.append("Total (Rs.) 7,04,850.00 0.00 0.00")
    return out


def part_b() -> list[str]:
    """Part B. Every figure sits at the end of its own line with two decimals,
    which is how the certificate prints and how the reader finds it."""
    return [
        "PART B (Annexure)",
        "Details of Salary Paid and any other income and tax deducted",
        "A Whether opting out of taxation u/s 115BAC(1A)? No",
        "1. Gross Salary Rs. Rs.",
        f"(a) Salary as per provisions contained in section 17(1) {GROSS_17_1}",
        f"(b) Value of perquisites under section 17(2) (as per Form No. 12BA, "
        f"wherever applicable) {PERQUISITES_17_2}",
        "(c) Profits in lieu of salary under section 17(3) (as per Form No. "
        "12BA, wherever applicable) 0.00",
        f"(d) Total {GROSS_SALARY}",
        "(e) Reported total amount of salary received from other employer(s) 0.00",
        "2. Less: Allowances to the extent exempt under section 10",
        "(a) Travel concession or assistance under section 10(5) 0.00",
        "(b) House rent allowance under section 10(13A) 0.00",
        "8. Deductions under section 16",
        f"(a) Standard deduction under section 16(ia) {STANDARD_DEDUCTION}",
        "(b) Entertainment allowance under section 16(ii) 0.00",
        "(c) Tax on employment under section 16(iii) 0.00",
        f"9. Gross total income (6+8) {GROSS_TOTAL_INCOME}",
        "10. Deductions under Chapter VI-A Gross Amount Deductible Amount",
        "(c) scheme under section 80CCD (1) 0.00 0.00",
        "(d) Total deduction under section 80C, 80CCC and 80CCD(1) 0.00 0.00",
        f"12. Total taxable income (9-11) {GROSS_TOTAL_INCOME}",
        f"13. Tax on total income {TAX_ON_TOTAL_INCOME}",
        f"14. Rebate under section 87A, if applicable {REBATE_87A}",
        "16. Health and education cess 0.00",
        "21. Net tax payable (17-18-19-20) 0.00",
    ]


def write_pdf(path: str, pages: list[list[str]]) -> None:
    """A multi-page PDF. Page count matters here: the Part B marker has to be
    reachable only by reading past the cover sheet."""
    objs: dict[int, bytes] = {}
    page_ids, content_ids = [], []
    next_id = 4
    for lines in pages:
        page_ids.append(next_id)
        content_ids.append(next_id + 1)
        next_id += 2
    font_id = next_id

    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = b" ".join(b"%d 0 R" % p for p in page_ids)
    objs[2] = (b"<< /Type /Pages /Count %d /Kids [%s] >>"
               % (len(page_ids), kids))

    for page_id, content_id, lines in zip(page_ids, content_ids, pages):
        ops = [b"BT /F1 8 Tf 12 TL 20 1560 Td"]
        for line in lines:
            escaped = (line.replace("\\", r"\\")
                           .replace("(", r"\(").replace(")", r"\)"))
            ops.append(b"(" + escaped.encode("latin-1") + b") Tj T*")
        ops.append(b"ET")
        content = b"\n".join(ops) + b"\n"
        objs[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1200 1600] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (font_id, content_id))
        objs[content_id] = (b"<< /Length %d >>\nstream\n" % len(content)
                            + content + b"\nendstream")
    objs[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for n in sorted(objs):
        offsets[n] = len(out)
        out += b"%d 0 obj\n" % n + objs[n] + b"\nendobj\n"
    xref = len(out)
    highest = max(objs)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (highest + 1)
    for n in range(1, highest + 1):
        out += b"%010d 00000 n \n" % offsets.get(n, 0)
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (highest + 1, xref))
    with open(path, "wb") as fh:
        fh.write(bytes(out))


def main() -> int:
    pages = [cover_page(), part_a(), part_b()]
    write_pdf("form16_employer_synthetic.pdf", pages)
    squashed = "".join("".join("".join(page) for page in pages).split())
    marker = squashed.lower().find("partb(annexure)")
    print("wrote form16_employer_synthetic.pdf")
    print(f"  {len(pages)} pages")
    print(f"  Part B marker at squashed offset {marker} "
          f"(must be > 4000 for the fixture to test anything)")
    print(f"  gross salary {GROSS_SALARY}, quarterly amounts sum to the same")
    return 0


if __name__ == "__main__":
    sys.exit(main())
