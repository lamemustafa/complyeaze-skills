#!/usr/bin/env python3
"""
Take identifiers out of anything about to be printed. Standard library only.

    from redact import safe_name, strip_identifiers

Why this is its own file
------------------------
Every script here promises not to reproduce a PAN, an Aadhaar number, a TAN or
an account number, and every one of them was breaking that promise in the same
place: **the file name**. The portal names its downloads after the taxpayer.

    <PAN>-Prefill-2026-28_61_2026_17_3.json
    <PAN>_upload_2026-27...json
    Form168_<PAN>_2026-27.pdf
    ACK<15-digit acknowledgement number>.pdf

Those identifiers were being copied verbatim into every result, every refusal
message
and every `--json` file, by scripts whose disclaimers said no identifier is
reproduced. A promise kept in nine places and broken in the tenth is not kept,
so the redaction lives in one place and each script calls it.

What it does not do
-------------------
It is not a scrubber for free text and must not be used as one. It removes
things with a fixed and checkable shape — PAN, TAN, Aadhaar, IFSC, long digit
runs — and it will not notice a name, an address or an email. Anything shaped
loosely enough to need judgement is not printed at all rather than passed
through this.
"""
from __future__ import annotations

import os
import re

# Shapes with a defined format, so a match is a match rather than a guess.
#
# The boundaries are lookarounds on letters and digits, not \b. A file name
# separates its parts with underscores, and `_` is a word character, so \b
# never fires inside one: `Form168_<PAN>_2026-27.pdf` went straight through a
# \b-anchored PAN pattern with the PAN intact. That is the exact bug this module
# exists for, and the first draft of it had the bug too.
EDGE = (r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])")
PAN = re.compile(EDGE[0] + r"[A-Z]{5}[0-9]{4}[A-Z]" + EDGE[1])
TAN = re.compile(EDGE[0] + r"[A-Z]{4}[0-9]{5}[A-Z]" + EDGE[1])
AADHAAR = re.compile(EDGE[0] + r"[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}" + EDGE[1])
IFSC = re.compile(EDGE[0] + r"[A-Z]{4}0[A-Z0-9]{6}" + EDGE[1])
LONG_DIGITS = re.compile(r"(?<![0-9])[0-9]{9,}(?![0-9])")

# What a file name can carry. An IFSC is branch routing data rather than a
# personal identifier, and it does not appear in a portal file name; leaving it
# out keeps an ordinary name that happens to fit the shape from being mangled.
IN_FILENAMES = (PAN, TAN, AADHAAR, LONG_DIGITS)
ALL_SHAPES = (PAN, TAN, AADHAAR, IFSC, LONG_DIGITS)

MASK = "<redacted>"


def strip_identifiers(text: str, mask: str = MASK, patterns=ALL_SHAPES) -> str:
    """Replace every fixed-shape identifier in `text`."""
    if not text:
        return text
    for pattern in patterns:
        text = pattern.sub(mask, text)
    return text


def safe_name(path: str) -> str:
    """The base name of `path`, with any identifier in it masked.

    The extension and the rest of the name survive, because the name is how a
    person tells one of their files from another:

        ABCDE1234F-Prefill-2026-28.json  ->  <redacted>-Prefill-2026-28.json
    """
    return strip_identifiers(os.path.basename(path), patterns=IN_FILENAMES)


if __name__ == "__main__":
    import sys
    for argument in sys.argv[1:] or [
            "ABCDE1234F-Prefill-2026-28_61_2026_17_3.json",
            "Form168_ABCDE1234F_2026-27.pdf",
            "ABCDE1234F_2025-26_AIS.pdf",
            "ACK100000000000001.pdf",
            "100000000000002.json",
            "taxpnl-GB1052-2025_2026-Q1-Q4.xlsx",
            "kotak.pdf"]:
        print(f"{argument}  ->  {safe_name(argument)}")
