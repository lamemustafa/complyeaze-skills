#!/usr/bin/env python3
"""
Rebuild the synthetic AIS fixture. Standard library only.

    python3 build_ais_synthetic.py

The layout is copied from a real AY 2026-27 AIS: Part B1 with a salary code and
its quarterly rows, and Part B2 with savings-bank interest broken out one row
per account, and sale of securities broken out one row per disposal.

The content is invented. The scrip names and ISINs are real, because they are
public market data, and the repository already treats them that way in the
broker fixtures. The reporting entities' TANs are placeholders and no figure is
anybody's. The account numbers begin with a 1 on purpose: an Aadhaar number
never starts with 0 or 1, and an earlier draft used twelve 9s, which the PII
scanner correctly read as an Aadhaar number and refused to ship.

What the fixture is for
-----------------------
Two things AIS carries that a category total cannot say.

**Which account.** SFT-016(SB) is a separate block per bank, so the AIS itself
tells you which banks reported and how much each one reported. That is the
first place to look when the statements do not add up to the AIS figure: a
bank present in AIS and absent from the statements, or the other way round.

**Which trade.** SFT-17 gives one row per disposal with the date, the scrip,
the ISIN, whether it was short or long term, and the consideration. The
category total already reconciled against TIS; what it could never do was let a
broker statement be matched line by line.

Both tables print an account number or a client ID, so the fixture also exists
to prove those never reach the output.
"""
import sys

# Part B1: salary, with quarterly detail.
SALARY_ROWS = [
    ("1", "Q1(Apr-Jun)", "25/06/2025", "2,80,000", "19,500", "19,500"),
    ("2", "Q2(Jul-Sep)", "26/09/2025", "2,80,000", "19,500", "19,500"),
    ("3", "Q3(Oct-Dec)", "24/12/2025", "2,80,000", "19,500", "19,500"),
    ("4", "Q4(Jan-Mar)", "25/03/2026", "2,80,000", "19,500", "19,500"),
]

# Part B2: savings interest, one block per reporting bank.
#
# The bank names are real ones because the reconciliation has to match a
# reporter's printed name against a bank identified from a statement's IFSC, and
# "SPECIMEN BANK LIMITED" exercises none of that. The figures are invented, and
# chosen to reproduce the shape of the problem this fixture exists for: the HDFC
# figure is exactly what bank_statement_dotted_synthetic.pdf credits, so that one
# ties, and the other three are banks with no statement at all. The difference
# between the AIS total and the statements is then the three missing accounts,
# which is what an unexplained shortfall on a real return turns out to be.
SAVINGS = [
    ("HDFC BANK LIMITED (AAAA00000A.AB001)", "28/05/2026", "122222222201", "1,950"),
    ("KOTAK MAHINDRA BANK LIMITED (BBBB11111B.AB002)", "12/05/2026", "122222222202", "725"),
    ("STANDARD CHARTERED BANK (CCCC22222C.AB003)", "02/06/2026", "122222222203", "640"),
    ("DCB BANK LIMITED (DDDD33333D.AB004)", "27/05/2026", "122222222204", "85"),
]

# Part B2: sale of listed equity. quantity, price/unit, consideration, cost,
# FMV/unit, FMV, indexed cost. The displayed considerations add to 12,408 while
# the summary states 12,407. AIS rounds each row to whole rupees and computes
# the total from the unrounded figures, so the two differ by up to half a rupee per row; on a
# real AIS 108 disposals reconciled to within ₹4. The reconciliation has to
# tolerate that much and no more.
SECURITIES = [
    ("1", "29/04/2025", "MPS  LIMITED-EQUITY SHARES(INE943D01017)", None,
     "Listed", "EquityShare", "Market", "Market", "Short", "term",
     "3.00", "1,710.20", "5,131", "5,055.45", "605.30", "1,815.90", "0"),
    ("2", "14/05/2025",
     "GOKALDAS   EXPORTS  LIMITED -NEW  EQUITY SHARES  OF",
     "RS. 5/-AFTER  SPLIT(INE887G01027)",
     "Listed", "EquityShare", "Market", "Market", "Short", "term",
     "8.00", "786.45", "6,292", "6,410.10", "135.20", "1,081.60", "0"),
    ("3", "18/09/2025", "SKIPPER  LIMITED-EQUITY SHARES(INE439E01022)", None,
     "Listed", "EquityShare", "Market", "Off market", "Long", "term",
     "2.00", "492.35", "985", "910.40", "138.75", "277.50", "0"),
]
SECURITIES_TOTAL = "12,407"
SAVINGS_TOTAL = "3,400"


# One column specification, used to lay out both the header and the rows, so the
# two cannot drift apart. An earlier draft hand-aligned them and the ASSET
# column landed over the CREDIT column's values — the fixture then "passed"
# while reading every disposal's term as "market".
SUMMARY_COLS = [("SR. NO.", 10, "<"), ("INFORMATION  CODE", 27, "<"),
                ("INFORMATION   DESCRIPTION", 38, "<"),
                ("INFORMATION  SOURCE", 44, "<"),
                ("COUNT", 8, ">"), ("AMOUNT", 14, ">")]

SAVINGS_COLS = [("SR.NO.", 10, "<"), ("REPORTED  ON", 27, "<"),
                ("ACCOUNT  NUMBER", 30, "<"), ("ACCOUNT   TYPE", 26, "<"),
                ("INTEREST  AMOUNT", 20, ">"), ("STATUS", 12, "<")]

QUARTER_COLS = [("SR.NO.", 10, "<"), ("QUARTER", 27, "<"),
                ("DATE OF PAYMENT/  CREDIT", 30, "<"),
                ("AMOUNT  PAID/ CREDITED", 26, ">"),
                ("TDS DEDUCTED", 18, ">"), ("TDS DEPOSITED", 18, ">"),
                ("STATUS", 12, "<")]

SECURITY_COLS = [("SR.", 6, "<"), ("DATE  OFSALE/", 14, "<"),
                 ("SECURITY  NAME  (SECURITY CODE)", 72, "<"),
                 ("SECURITY", 14, "<"), ("DEBIT", 11, "<"),
                 ("CREDIT", 12, "<"), ("ASSET", 11, "<"),
                 ("QUANTITY", 11, ">"), ("SALE  PRICE", 13, ">"),
                 ("SALES", 15, ">"), ("COST OF", 14, ">"),
                 ("UNIT", 12, ">"), ("FAIR", 14, ">"),
                 ("INDEXED COST", 15, ">"), ("STATUS", 10, "<")]


def lay(cols, values):
    out = []
    for (label, width, align), value in zip(cols, values):
        text = "" if value is None else str(value)
        out.append(f"{text:{align}{width}}")
    # Four spaces between columns: the reader groups header words that are
    # three spaces or fewer apart into one label, so a one-space gap merged
    # "INTEREST AMOUNT" and "STATUS" into a single column.
    return "    " + "    ".join(out).rstrip()


def header(cols):
    return lay(cols, [label for label, _, _ in cols])


def page_header():
    return [
        "  AnnualInformationStatement (AIS)                    FinancialYear  2025-26",
        "  PartA -GeneralInformation",
        "  Permanent Account Number  (PAN)      Aadhaar Number       Name  ofAssessee",
        "  ABCDE1234F                      XXXX XXXX  0000      SPECIMEN  FIXTURE",
        "",
    ]


def part_b1():
    out = [
        "  PartB1-Informationrelatingtotaxdeducted orcollectedatsource",
        "  Salary",
        header(SUMMARY_COLS),
        lay(SUMMARY_COLS, ["1", "TDS-192", "Salaryreceived(Section192)",
                           "SPECIMEN EMPLOYER (AAAA00000A)", "4", "11,20,000"]),
        header(QUARTER_COLS),
    ]
    for serial, quarter, date, paid, deducted, deposited in SALARY_ROWS:
        out.append(lay(QUARTER_COLS, [serial, quarter, date, paid, deducted,
                                      deposited, "Active"]))
    return out


def part_b2():
    out = ["  PartB2-Informationrelatingtospecifiedfinancialtransaction(SFT)",
           "  Interestfromsavingbank"]
    for source, reported, account, amount in SAVINGS:
        out += [
            header(SUMMARY_COLS),
            lay(SUMMARY_COLS, ["1", "SFT-016(SB)",
                               "Interestincome (SFT-016)-Savings", source,
                               "1", amount]),
            header(SAVINGS_COLS),
            lay(SAVINGS_COLS, ["1", reported, account, "Saving", amount,
                               "Active"]),
        ]
    out += [
        "  Saleof securitiesandunitsofmutualfund",
        header(SUMMARY_COLS),
        lay(SUMMARY_COLS, ["1", "SFT-17-LES(M)",
                           "Sale oflistedequityshare(Depository)",
                           "SPECIMEN  DEPOSITORY (EEEE44444E)", "3",
                           SECURITIES_TOTAL]),
        header(SECURITY_COLS),
    ]
    for row in SECURITIES:
        (serial, date, name, name2, klass, klass2, debit, credit,
         asset, asset2, qty, price, consideration, cost, fmv_unit,
         fmv, indexed) = row
        out.append(lay(SECURITY_COLS,
                       [serial, date, name, klass, debit, credit, asset, qty,
                        price, consideration, cost, fmv_unit, fmv, indexed,
                        "Active"]))
        out.append(lay(SECURITY_COLS,
                       [None, None, name2, klass2, None, None, asset2]))
    return out


def write_pdf(path: str, text_lines: list[str]) -> None:
    ops = [b"BT /F1 6 Tf 20 TL 12 1580 Td"]
    for line in text_lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ops.append(b"(" + escaped.encode("latin-1") + b") Tj T*")
    ops.append(b"ET")
    content = b"\n".join(ops) + b"\n"
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 2400 1600] /Resources "
           b"<< /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        4: b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    }
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for n in sorted(objs):
        offsets[n] = len(out)
        out += b"%d 0 obj\n" % n + objs[n] + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for n in sorted(objs):
        out += b"%010d 00000 n \n" % offsets[n]
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref))
    with open(path, "wb") as fh:
        fh.write(bytes(out))


def main() -> int:
    write_pdf("ais_synthetic.pdf", page_header() + part_b1() + part_b2()
              + ["  Download  ID :ABCDE1234F202607211735",
                 "  Gener ationDate :21/07/2026,17:35:12                     Page 1 of1"])
    print("wrote ais_synthetic.pdf")
    print(f"  savings interest across {len(SAVINGS)} banks: {SAVINGS_TOTAL}")
    print(f"  {len(SECURITIES)} disposals stated as {SECURITIES_TOTAL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
