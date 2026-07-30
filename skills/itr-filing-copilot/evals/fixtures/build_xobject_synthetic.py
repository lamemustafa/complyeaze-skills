#!/usr/bin/env python3
"""Rebuild the synthetic Form-XObject-wrapped PDF fixtures. Standard library only.

    python3 build_xobject_synthetic.py

[observed 2026-07-31, one real employer-issued Form 16] A PDF may draw almost
nothing in its page ``/Contents`` and put the whole document inside a Form
XObject that the page invokes with ``Do``. The observed page content stream was
144 bytes: a page-number footer and ``/Xf1 Do``. Reading only ``/Contents``
returned the four characters ``1of9`` for a nine-page certificate and the
document was then refused as undecodable.

Enterprise PDF writers do this routinely — payroll systems, TRACES, and portal
exports all compose a page from reusable form objects. Every figure below is
invented; the shape is not.

Three fixtures are written:

``xobject_wrapped_synthetic.pdf``
    Two pages. Each page's own content stream holds only a footer drawn with
    ``/F1``. The body of each page lives in a Form XObject carrying its own
    ``/Resources`` and its own font ``/F2``, so a reader that does not merge
    XObject resources decodes the footer and loses the table.

``xobject_nested_synthetic.pdf``
    The Form XObject invokes a second Form XObject, which holds the figure that
    matters. Proves the walk recurses rather than stopping one level down.

``xobject_cycle_synthetic.pdf``
    Two Form XObjects that invoke each other. A walk without a visited set does
    not terminate on this file.
"""
from __future__ import annotations

import sys


def _obj(number: int, body: bytes) -> bytes:
    return b"%d 0 obj\n" % number + body + b"\nendobj\n"


def _stream(dictionary: bytes, payload: bytes) -> bytes:
    return (b"<< " + dictionary + b" /Length %d >>\nstream\n" % len(payload)
            + payload + b"\nendstream")


def _text_ops(font: bytes, rows: list[tuple[int, int, str]]) -> bytes:
    """Draw each (x, y, text) with `font`, one text object per row."""
    out = bytearray()
    for x, y, text in rows:
        escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        out += (b"BT\n/" + font + b" 10 Tf\n1 0 0 1 %d %d Tm\n(" % (x, y)
                + escaped.encode("latin-1") + b") Tj\nET\n")
    return bytes(out)


def _assemble(objects: dict[int, bytes], root: int) -> bytes:
    """Serialise numbered objects with a correct xref table and trailer."""
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += _obj(number, objects[number])
    start = len(out)
    top = max(objects) + 1
    out += b"xref\n0 %d\n" % top
    out += b"0000000000 65535 f \n"
    for number in range(1, top):
        if number in offsets:
            out += b"%010d 00000 n \n" % offsets[number]
        else:
            out += b"0000000000 65535 f \n"
    out += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (top, root, start))
    return bytes(out)


# The body every reader must recover. Invented figures, deliberately in the
# shape of a salary certificate so a bucket-style assertion has something to
# hold on to.
BODY_ROWS_PAGE_ONE = [
    (60, 720, "SYNTHETIC EMPLOYER PRIVATE LIMITED"),
    (60, 700, "Certificate under Section 203"),
    (60, 680, "Gross Salary 1111.11"),
    (60, 660, "Standard deduction 222.22"),
]
BODY_ROWS_PAGE_TWO = [
    (60, 720, "Deductions under Chapter VI-A"),
    (60, 700, "Aggregate deductible amount 333.33"),
    (60, 680, "Total taxable income 4444.44"),
]

FOOTER_ONLY = "1 of 2"


def build_wrapped() -> bytes:
    """Page content is a footer; the table is one Form XObject deep."""
    font_footer = _obj_font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica " \
                              b"/Encoding /WinAnsiEncoding >>"
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [4 0 R 5 0 R] /Count 2 >>",
        3: font_footer,
    }
    # 6,7  page content streams (footer only)   8,9  form xobjects (the body)
    objects[6] = _stream(b"", _text_ops(b"F1", [(280, 34, FOOTER_ONLY)])
                         + b"q 1 0 0 1 0 0 cm /Xf1 Do Q\n")
    objects[7] = _stream(b"", _text_ops(b"F1", [(280, 34, "2 of 2")])
                         + b"q 1 0 0 1 0 0 cm /Xf1 Do Q\n")
    objects[8] = _stream(
        b"/Type /XObject /Subtype /Form /BBox [0 0 612 792] "
        b"/Resources << /Font << /F2 3 0 R >> >>",
        _text_ops(b"F2", BODY_ROWS_PAGE_ONE))
    objects[9] = _stream(
        b"/Type /XObject /Subtype /Form /BBox [0 0 612 792] "
        b"/Resources << /Font << /F2 3 0 R >> >>",
        _text_ops(b"F2", BODY_ROWS_PAGE_TWO))
    objects[4] = (b"<< /Type /Page /Parent 2 0 R /Contents 6 0 R /Resources "
                  b"<< /Font << /F1 3 0 R >> /XObject << /Xf1 8 0 R >> >> >>")
    objects[5] = (b"<< /Type /Page /Parent 2 0 R /Contents 7 0 R /Resources "
                  b"<< /Font << /F1 3 0 R >> /XObject << /Xf1 9 0 R >> >> >>")
    return _assemble(objects, 1)


def build_nested() -> bytes:
    """The figure that matters sits two Form XObjects deep."""
    font = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>")
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        3: font,
    }
    objects[6] = _stream(b"", _text_ops(b"F1", [(280, 34, "1 of 1")])
                         + b"/Xf1 Do\n")
    objects[7] = _stream(
        b"/Type /XObject /Subtype /Form /BBox [0 0 612 792] "
        b"/Resources << /Font << /F2 3 0 R >> /XObject << /Xf2 8 0 R >> >>",
        _text_ops(b"F2", [(60, 720, "Outer form object")]) + b"/Xf2 Do\n")
    objects[8] = _stream(
        b"/Type /XObject /Subtype /Form /BBox [0 0 612 792] "
        b"/Resources << /Font << /F3 3 0 R >> >>",
        _text_ops(b"F3", [(60, 700, "Nested total 5555.55")]))
    objects[4] = (b"<< /Type /Page /Parent 2 0 R /Contents 6 0 R /Resources "
                  b"<< /Font << /F1 3 0 R >> /XObject << /Xf1 7 0 R >> >> >>")
    return _assemble(objects, 1)


def build_cycle() -> bytes:
    """Two Form XObjects that invoke each other. Must terminate, not hang."""
    font = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>")
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        3: font,
    }
    objects[6] = _stream(b"", _text_ops(b"F1", [(280, 34, "1 of 1")]) + b"/Xa Do\n")
    objects[7] = _stream(
        b"/Type /XObject /Subtype /Form /BBox [0 0 612 792] "
        b"/Resources << /Font << /F2 3 0 R >> /XObject << /Xb 8 0 R >> >>",
        _text_ops(b"F2", [
            (60, 720, "Cycle side A 6666.66"),
            (60, 706, "This side invokes the other and carries ordinary prose so"),
            (60, 692, "that the document density gate sees a normal page rather"),
            (60, 678, "than a sparse one, keeping this fixture about termination."),
        ]) + b"/Xb Do\n")
    objects[8] = _stream(
        b"/Type /XObject /Subtype /Form /BBox [0 0 612 792] "
        b"/Resources << /Font << /F2 3 0 R >> /XObject << /Xa 7 0 R >> >>",
        _text_ops(b"F2", [
            (60, 650, "Cycle side B 7777.77"),
            (60, 636, "This side invokes the first one straight back again, so a"),
            (60, 622, "walk with no visited set never returns from this file at"),
            (60, 608, "all and the reader hangs instead of refusing honestly."),
        ]) + b"/Xa Do\n")
    objects[4] = (b"<< /Type /Page /Parent 2 0 R /Contents 6 0 R /Resources "
                  b"<< /Font << /F1 3 0 R >> /XObject << /Xa 7 0 R >> >> >>")
    return _assemble(objects, 1)


FIXTURES = {
    "xobject_wrapped_synthetic.pdf": build_wrapped,
    "xobject_nested_synthetic.pdf": build_nested,
    "xobject_cycle_synthetic.pdf": build_cycle,
}


def main() -> int:
    for name, build in FIXTURES.items():
        with open(name, "wb") as fh:
            fh.write(build())
        print(f"wrote {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
