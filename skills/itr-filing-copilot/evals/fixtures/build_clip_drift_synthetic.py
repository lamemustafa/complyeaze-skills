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
    real   Helvetica widths end the run near x 166   (inside the clip)
    guess  char_w 0.5 ends it near x 250            (outside)

The invariant is asserted when the file is built, so the fixture cannot quietly
stop demonstrating anything: real_end < clip_right < estimated_end. Without it a
string merely long enough to leave the box would be clipped correctly by any
reader, and the assertion in test_parsers.py would keep passing after #32 is
fixed — proving the opposite of what it claims.

Expected today: the tail is missing. When #32 is fixed by reading the font's own
/Widths, the whole string comes back and this fixture stops being a
demonstration and starts being a regression test.
"""
import os

# Deliberately narrow glyphs. `read_pdf.py` advances the clip probe by a flat
# 0.5 em per character; `[documented]` Helvetica's `i`, `l`, `t` and space are
# 0.222-0.278 em in Adobe's AFM metrics for the base-14 fonts,
# so the estimate outruns the real text by nearly half the run's length. That
# gap is the whole fixture: a wider string would leave the clip legitimately,
# and then a width-aware reader would drop the tail too and the fixture would
# prove nothing.
TEXT = "little titles fit; illicit lists fill it"

# Helvetica advance widths, per 1000 em, for the characters above.
# `[documented]` Adobe's Helvetica AFM metrics, which every conforming reader
# uses for the base-14 fonts: space and semicolon 278, f 278, i 222, l 222,
# t 278, c 500, e 556, s 500. The fixture's whole premise rests on these being
# far below the flat 0.5 em (500) the clip probe assumes, so a maintainer has to
# be able to tell where they came from.
HELVETICA = {" ": 278, ";": 278, "f": 278, "i": 222, "l": 222, "t": 278,
             "s": 500, "e": 556, "c": 500}
CLIP = (40, 630, 200, 660)
TEXT_X = 50
TEXT_Y = 640
FONT_SIZE = 10
# The font carries its own /Widths, first to last character used. #32 is fixed by
# reading these; a base-14 Helvetica with no /Widths would give that code nothing
# to consume, and the truncation assertion could stay green through the fix.
FIRST_CHAR = min(ord(c) for c in TEXT)
LAST_CHAR = max(ord(c) for c in TEXT)
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


def widths() -> list[int]:
    """/Widths for FIRST_CHAR..LAST_CHAR; anything unused takes a wide default,
    which cannot help the run pass — only the characters in TEXT matter."""
    return [HELVETICA.get(chr(code), 500)
            for code in range(FIRST_CHAR, LAST_CHAR + 1)]


def build() -> bytes:
    lines = [f"BT /F1 {FONT_SIZE} Tf 1 0 0 1 {TEXT_X} 760 Tm 14 TL"]
    lines += [f"({line}) Tj T*" for line in BODY]
    lines.append("ET")
    # The stream and check_invariant() read the SAME constants. With separate
    # copies the builder could pass its invariant while writing different
    # geometry — raising Tf to 15 would push the real run past the clip edge
    # while the check still reported an endpoint inside it.
    stream = ("\n".join(lines) + "\n"
              f"q\n{CLIP[0]} {CLIP[1]} {CLIP[2] - CLIP[0]} {CLIP[3] - CLIP[1]} re W n\n"
              f"BT /F1 {FONT_SIZE} Tf 1 0 0 1 {TEXT_X} {TEXT_Y} Tm "
              f"({TEXT}) Tj ET\nQ\n").encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        (b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
         b"/FirstChar %d /LastChar %d /Widths [%s] >>"
         % (FIRST_CHAR, LAST_CHAR,
            b" ".join(b"%d" % w for w in widths()))),
    ]
    # The binary marker stops Git and other text tooling treating an all-ASCII
    # PDF as text. A checkout with core.autocrlf=true rewrites every line ending,
    # which invalidates the byte-counted /Length and the xref offsets, and the
    # clipped run this fixture exists for is then lost before any test sees it.
    out = bytearray(b"%PDF-1.4\n%\x00\xe2\xe3\xcf\xd3\n")
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


def check_invariant() -> tuple[float, float]:
    """The run must fit its clip under real widths and not under the estimate."""
    real_end = TEXT_X + sum(HELVETICA[c] for c in TEXT) / 1000 * FONT_SIZE
    estimated_end = TEXT_X + len(TEXT) * FONT_SIZE * 0.5
    if not real_end < CLIP[2] < estimated_end:
        raise SystemExit(
            f"this fixture demonstrates nothing: real end {real_end:.1f}, clip "
            f"right {CLIP[2]}, estimated end {estimated_end:.1f}. The run has "
            "to fit the box under real glyph widths and miss it under the flat "
            "0.5 em estimate, or a width-aware reader would drop the tail too.")
    return real_end, estimated_end


if __name__ == "__main__":
    real_end, estimated_end = check_invariant()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUT)
    with open(path, "wb") as fh:
        fh.write(build())
    print(f"wrote {OUT}: {len(TEXT)} characters, clip x {CLIP[0]}-{CLIP[2]}, "
          f"real end {real_end:.1f}, estimated end {estimated_end:.1f}")
