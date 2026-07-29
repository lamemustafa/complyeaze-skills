#!/usr/bin/env python3
"""
Rebuild the synthetic bank-statement fixtures. Standard library only.

    python3 build_bank_statement_synthetic.py

Everything here is invented: the account number is not an account number, the
IFSC is a real branch prefix because that is public routing data, and no figure
comes from anybody's statement.

Two files are written, and each exists to reproduce a defect found on real
documents:

`bank_statement_dotted_synthetic.pdf` — dates written `23.04.2025`, the way
HDFC prints them. Two bugs met in that one string. The date pattern accepted
only `-` and `/`, so almost every row was skipped; a 58-page statement came back
with two transactions. And the amount pattern matched `23.04` inside the date,
so the rows that did survive carried a phantom ₹23.04. The fixture also holds a
₹80,000 *withdrawal*, which the old reader offered as a credit needing
explanation because it never looked at which way the balance moved.

`bank_statement_reverse_synthetic.pdf` — the same transactions printed
newest-first. Reading a reversed statement as though it ran forwards inverts
every credit into a debit and every debit into a credit, which is worse than not
reading it: the withdrawals become the receipts you have to explain.

Both must produce identical interest and identical credits.

`bank_statement_torn_synthetic.pdf` — the same statement with three rows
missing, as though a page failed to decode. This is the case nothing could
previously notice: the interest figure is still a plausible number, the credit
list is still a plausible list, and both are wrong. The running balance is the
only thing in a statement that cannot be reconciled unless every row between the
two ends was understood.

`bank_statement_crossyear_synthetic.pdf` — a statement running from January to
June, so it straddles 31 March, and narrating its quarterly interest as the bare
word `INTEREST`. Two defects meet here. The interest pattern was deliberately
narrow so a UPI payment to someone named Interest would not become income, and
it therefore missed a narration that is nothing but the word itself; four
quarterly credits on a real statement went uncounted. And nothing filtered by
financial year at all, so interest credited in March 2025 — which belongs to
AY 2025-26 — was added to the AY 2026-27 figure.
"""
import sys

# (date, narration, amount, balance_after) — invented, and internally consistent
# so the running balance is a real running balance.
OPENING = 10000.00
ROWS = [
    ("01.04.2025", "OPENING BALANCE B/F", None, 10000.00),
    ("23.04.2025", "UPI/CR/REF4012345/CONSULTING FEE", 50000.00, 60000.00),
    ("15.05.2025", "ATM WDL/AGRA/CARD 9012", -20000.00, 40000.00),
    ("30.06.2025", "CREDIT INTEREST CAPITALISED", 325.00, 40325.00),
    ("05.07.2025", "NEFT DR/OWN A/C TRANSFER", -15000.00, 25325.00),
    ("10.08.2025", "IMPS CR/GIFT FROM FAMILY", 75000.00, 100325.00),
    ("20.09.2025", "REFUND FROM MERCHANT ORDER 88213", 60000.00, 160325.00),
    ("30.09.2025", "SB INT CREDIT", 425.00, 160750.00),
    ("15.10.2025", "INT.COLL ON TEMP OVERDRAWN", -250.00, 160500.00),
    ("31.12.2025", "QUARTERLY INTEREST", 525.00, 161025.00),
    ("20.01.2026", "NEFT DR/RENT PAYMENT TO LANDLORD", -80000.00, 81025.00),
    ("31.03.2026", "INTEREST PAID", 675.00, 81700.00),
    # A statement prints both ends. Without a carried-forward line the reader
    # can only say that nothing was missed *between* the first and last rows it
    # read, which is a weaker claim than the one it wants to make.
    ("31.03.2026", "CLOSING BALANCE C/F", None, 81700.00),
]

HEADER = [
    "SPECIMEN BANK LIMITED - SYNTHETIC FIXTURE, NOT A REAL STATEMENT",
    "Branch IFSC HDFC0000123    Account XXXXXXXXXX    Currency INR",
    "Statement for the period 01.04.2025 To 31.03.2026",
    "",
    "Date         Narration                                Amount        Balance",
]


def indian(n: float) -> str:
    """1,60,950.00 — the grouping the amount pattern has to survive."""
    sign = "-" if n < 0 else ""
    whole, frac = f"{abs(n):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return f"{sign}{whole}.{frac}"


def lines(reverse: bool) -> list[str]:
    body = []
    for date, narration, amount, balance in ROWS:
        shown = "" if amount is None else indian(abs(amount))
        body.append(f"{date}   {narration:<40} {shown:>12}  {indian(balance):>12}")
    if reverse:
        # Newest first: the carried-forward line at the top and the
        # brought-forward line at the bottom, which is what a reversed
        # statement actually looks like.
        body = body[::-1]
    return HEADER + body


CROSS_YEAR = [
    ("01.01.2025", "OPENING BALANCE B/F", None, 50000.00),
    ("01.01.2025", "INTEREST", 900.00, 50900.00),
    ("15.02.2025", "UPI/CR/INTEREST SOLUTIONS PVT LTD", 71000.00, 121900.00),
    ("31.03.2025", "INTEREST", 1100.00, 123000.00),
    ("10.04.2025", "NEFT DR/CARD PAYMENT", -22000.00, 101000.00),
    ("30.06.2025", "INTEREST", 1300.00, 102300.00),
]


def cross_year_lines() -> list[str]:
    body = []
    for date, narration, amount, balance in CROSS_YEAR:
        shown = "" if amount is None else indian(abs(amount))
        body.append(f"{date}   {narration:<40} {shown:>12}  {indian(balance):>12}")
    head = list(HEADER)
    head[2] = "Statement for the period 01.01.2025 To 30.06.2025"
    return head + body


def torn_lines() -> list[str]:
    """The same statement with a run of rows missing, as though a page failed to
    decode. Every balance still printed, so interest and the credit list both
    look plausible — and the running balance no longer adds up, which is the
    only thing that can notice."""
    keep = [r for r in ROWS if r[0] not in ("05.07.2025", "10.08.2025",
                                            "20.09.2025")]
    body = []
    for date, narration, amount, balance in keep:
        shown = "" if amount is None else indian(abs(amount))
        body.append(f"{date}   {narration:<40} {shown:>12}  {indian(balance):>12}")
    return HEADER + body


def write_pdf(path: str, text_lines: list[str]) -> None:
    """A one-page PDF with a text layer, hand-assembled. No dependency."""
    ops = [b"BT /F1 9 Tf 12 TL 24 760 Td"]
    for line in text_lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ops.append(b"(" + escaped.encode("latin-1") + b") Tj T*")
    ops.append(b"ET")
    content = b"\n".join(ops) + b"\n"
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
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
    write_pdf("bank_statement_dotted_synthetic.pdf", lines(reverse=False))
    write_pdf("bank_statement_reverse_synthetic.pdf", lines(reverse=True))
    write_pdf("bank_statement_crossyear_synthetic.pdf", cross_year_lines())
    write_pdf("bank_statement_torn_synthetic.pdf", torn_lines())
    interest = sum(a for _, n, a, _ in ROWS
                   if a and a > 0 and "INT" in n.upper() and "INT.COLL" not in n)
    print("wrote bank_statement_dotted_synthetic.pdf, "
          "bank_statement_reverse_synthetic.pdf and "
          "bank_statement_crossyear_synthetic.pdf")
    print(f"  interest credited, by construction: {interest:,.2f}")
    print(f"  opening {OPENING:,.2f} -> closing {ROWS[-1][3]:,.2f}")
    print(f"  {len(ROWS)} rows including both balance-carry lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
