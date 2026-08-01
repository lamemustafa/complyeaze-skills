#!/usr/bin/env python3
"""Rebuild the synthetic CTM-scaled-text fixture. Standard library only.

    python3 build_text_scale_synthetic.py

[observed 2026-07-31, one real broker Tax P&L PDF] A PDF may carry its page
scale in the CTM, leave the text matrix at unity, and draw **one glyph per
``Tj``** with its own ``Tm``. Reading the glyph size off the text matrix then
yields 1.0 instead of the ``Tf`` size, the column unit collapses to a fraction
of a point, and every glyph lands roughly nineteen columns from its neighbour.

The document comes out as single letters separated by spaces:

    V i e w  Z e r o d h a ' s  g u i d e

which carries no word tokens at all, so the reader refuses a document whose
text it had in fact recovered correctly and in the right order.

The size a glyph is drawn at is the ``Tf`` size scaled by the text matrix and
then by the CTM. This fixture reproduces exactly that composition — CTM scale
0.3265, ``Tm`` at unity, one glyph per ``Tj`` — with invented text.

Every figure below is invented; the shape is not.
"""
from __future__ import annotations

import sys

from build_xobject_synthetic import _assemble, _stream

# Drawn one glyph at a time, the way the observed document does it. The x
# advance is a plausible per-character width at the composed size.
ROWS = [
    (56.0, 526.5, "Realized gains for the year"),
    (56.0, 512.0, "Non Equity Short Term profit 512.40"),
    (56.0, 497.5, "Non Equity Long Term profit 1380.25"),
    (56.0, 483.0, "Equity Intraday profit 0"),
]
CTM_SCALE = 0.32651079
TF_SIZE = 19.0
ADVANCE = 3.1          # device units per glyph: half the composed
                       # size, matching the reader's char_w


def _glyph_ops(font: bytes) -> bytes:
    out = bytearray()
    for x0, y, text in ROWS:
        for index, ch in enumerate(text):
            if ch == " ":
                continue
            escaped = ch.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            # Coordinates are in the CTM's space, so divide the device position
            # back out by the scale the CTM applies.
            x = (x0 + index * ADVANCE) / CTM_SCALE
            out += (b"BT\n/" + font + b" %g Tf\n" % TF_SIZE
                    + b"1 0 0 1 %.4f %.4f Tm\n(" % (x, y / CTM_SCALE)
                    + escaped.encode("latin-1") + b") Tj\nET\n")
    return bytes(out)


def build() -> bytes:
    font = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>")
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        3: font,
    }
    objects[6] = _stream(
        b"",
        b"q %.8f 0 0 %.8f 0 0 cm\n" % (CTM_SCALE, CTM_SCALE)
        + _glyph_ops(b"F1") + b"Q\n")
    objects[4] = (b"<< /Type /Page /Parent 2 0 R /Contents 6 0 R /Resources "
                  b"<< /Font << /F1 3 0 R >> >> >>")
    return _assemble(objects, 1)


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    name = "text_scale_synthetic.pdf"
    with open(os.path.join(here, name), "wb") as fh:
        fh.write(build())
    print(f"wrote {name}", file=sys.stderr)
