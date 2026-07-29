#!/usr/bin/env python3
"""Rebuild the synthetic TIS fixture from invented category totals.

    python3 build_tis_synthetic.py

Standard library only. The builder is the source of truth: the committed PDF
is never edited by hand, and none of its monetary figures came from a taxpayer.
"""
import sys


CATEGORIES = [
    ("1", "Dividend", "4,280"),
    ("2", "Interest from savings bank", "8,745"),
    ("3", "Receipt of accumulated balance of pf", "5,43,210"),
    ("4", "Sale of securities and units of mutual fund", "8,76,540"),
    ("5", "Purchase of securities and units of mutual funds", "7,65,430"),
]


def lines() -> list[str]:
    out = [
        "Taxpayer Information Summary (TIS)          Financial Year  2025-26",
        "SYNTHETIC FIXTURE - invented figures, no real taxpayer",
        "SR. NO.   INFORMATION CATEGORY            PROCESSED BY SYSTEM   ACCEPTED BY TAXPAYER",
    ]
    for serial, category, amount in CATEGORIES:
        out.append(f"{serial:<9} {category:<43} {amount:>19} {amount:>21}")
    return out


def write_pdf(path: str, text_lines: list[str]) -> None:
    """Write one text-layer page without any third-party dependency."""
    ops = [b"BT /F1 8 Tf 16 TL 24 760 Td"]
    for line in text_lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        ops.append(b"(" + escaped.encode("latin-1") + b") Tj T*")
    ops.append(b"ET")
    content = b"\n".join(ops) + b"\n"
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1200 792] /Resources "
           b"<< /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        4: b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    }
    # The binary marker makes Git and other text tooling treat the generated
    # artifact as a PDF rather than linting structural xref padding as prose.
    out = bytearray(b"%PDF-1.4\n%\x00\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for number in sorted(objs):
        offsets[number] = len(out)
        out += b"%d 0 obj\n" % number + objs[number] + b"\nendobj\n"
    xref = len(out)
    out += b"xref\r\n0 %d\r\n0000000000 65535 f\r\n" % (len(objs) + 1)
    for number in sorted(objs):
        out += b"%010d 00000 n\r\n" % offsets[number]
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref))
    with open(path, "wb") as fh:
        fh.write(bytes(out))


def main() -> int:
    write_pdf("tis_synthetic.pdf", lines())
    print("wrote tis_synthetic.pdf from 5 invented category totals")
    return 0


if __name__ == "__main__":
    sys.exit(main())
