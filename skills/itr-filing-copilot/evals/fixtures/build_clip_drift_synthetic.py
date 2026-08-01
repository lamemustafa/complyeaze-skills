#!/usr/bin/env python3
"""A string that fits its clip box, but whose ESTIMATED extent does not.

    python3 build_clip_drift_synthetic.py

Why this exists
---------------
`read_pdf.py` decides per-glyph visibility from `char_w = 0.5`, a guessed
average glyph width. Where the guess overshoots a string's true extent, the tail
of a perfectly visible run is dropped and never reported.

`[observed 2026-07-31, one real employer Form 16]` 96 characters lost that way,
including a run of statutory boilerplate, and a label fused into an amount —
which is the worse outcome, because a wrong figure does not look like a gap.

This file reproduces the mechanism with no identifier and no real figure. The
run starts inside the clip box and ends inside it under any realistic set of
glyph widths; only the 0.5 estimate walks it past the right edge.

    clip   x 40 -> 200, y 630 -> 660
    text   starts x 50 y 640, /F1 10 Tf, text matrix at unity
    real   a ~0.30 em face ends near x 173   (inside)
    guess  char_w 0.5 ends near x 255        (outside)

Expected today: the tail is missing. When #32 is fixed by reading the font's own
/Widths, the whole string comes back and this fixture stops being a
demonstration and starts being a regression test.
"""
import os

TEXT = "section 119 of the Income-tax Act 1961 xx"
CLIP = (40, 630, 200, 660)
OUT = "clip_drift_synthetic.pdf"


# Ordinary unclipped body text, so the page reads like a page and clears the
# word-density and letters-in-words gates. The defect is in the clipped run
# below it, not in whether the file is readable at all.
BODY = [
    "SPECIMEN CERTIFICATE UNDER RULE 31",
    "This certificate is issued under the provisions of the Act and the rules",
    "made under it. The particulars below are furnished for the previous year",
    "and have been verified against the records held by the deductor.",
    "The amounts shown are illustrative and belong to no person.",
]


def build() -> bytes:
    lines = ["BT /F1 10 Tf 1 0 0 1 50 760 Tm 14 TL"]
    lines += [f"({line}) Tj T*" for line in BODY]
    lines.append("ET")
    stream = ("\n".join(lines) + "\n"
              f"q\n{CLIP[0]} {CLIP[1]} {CLIP[2] - CLIP[0]} {CLIP[3] - CLIP[1]} re W n\n"
              f"BT /F1 10 Tf 1 0 0 1 50 640 Tm ({TEXT}) Tj ET\nQ\n").encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, xref))
    return bytes(out)


if __name__ == "__main__":
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUT)
    with open(path, "wb") as fh:
        fh.write(build())
    print(f"wrote {OUT}: {len(TEXT)} characters, clip x {CLIP[0]}-{CLIP[2]}")
