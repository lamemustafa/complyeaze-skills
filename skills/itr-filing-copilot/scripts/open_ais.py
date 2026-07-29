#!/usr/bin/env python3
"""
Work out the password an income-tax portal PDF opens with, and prove it opens.

Standard library only. Reads nothing but the file you name. No network.

    python3 open_ais.py AIS.pdf --pan ABCDE1234F --dob 01/01/1990
    python3 open_ais.py AIS.pdf --pan ABCDE1234F --dob 01011990 --print-password

The password is the taxpayer's PAN in lowercase followed by their date of birth
as ddmmyyyy, with no separator: PAN `ABCDE1234F` born 1 January 1990 gives that
PAN lowercased with `01011990` appended. AIS, TIS, the s.143(1) intimation and
most Form 16s all use it. `[observed]` on live AY 2026-27 downloads.

Nothing here writes a worked example of a complete password, and the readers
take `--password-stdin` so one never has to be typed on a command line. A
password in argv is readable by any other process on the machine through `ps`,
and it lands in the shell history besides.

The AIS **JSON** download is said to use the same credential, but that is
`[UNVERIFIED]` here: it arrives as an encrypted archive rather than a PDF, no
such file has been put through this project, and nothing in it reads one. Do not
rely on the claim until someone has tried it.

It does not write a decrypted copy, on purpose
----------------------------------------------
An earlier version wrote `AIS_decrypted.pdf` next to the original. That leaves a
document holding a PAN, an Aadhaar number, every bank account and a full year of
transactions sitting unprotected in a Downloads folder, usually forgotten. There
is no need for it: `read_pdf.py`, `parse_tax_docs.py` and `parse_bank_statement.py`
all take `--password` and decrypt in memory as they read.

    python3 open_ais.py AIS.pdf --pan ABCDE1234F --dob 01/01/1990 --print-password \\
        | python3 parse_tax_docs.py AIS.pdf TIS.pdf --password-stdin

What this script is for is the step before that — confirming the password is
right, and telling you which one opened it. A portal PDF accepts the owner
password as well as the user password, and knowing which one you used matters
when a file will not open: the wrong date of birth and the wrong PAN fail
identically otherwise.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdf_crypt import CryptError, is_encrypted, make_decryptor  # noqa: E402
from redact import safe_name  # noqa: E402

PAN_RE = re.compile(r"^[A-Za-z]{5}[0-9]{4}[A-Za-z]$")


def password(pan: str, dob: str) -> str:
    pan = pan.strip()
    if not PAN_RE.match(pan):
        raise SystemExit(f"'{pan}' is not a PAN. Expected 5 letters, 4 digits, 1 letter.")
    digits = re.sub(r"\D", "", dob)
    if len(digits) != 8:
        raise SystemExit(f"'{dob}' is not a date. Expected ddmmyyyy, dd/mm/yyyy or dd-mm-yyyy.")
    day, month = int(digits[:2]), int(digits[2:4])
    if not (1 <= day <= 31 and 1 <= month <= 12):
        raise SystemExit(
            f"'{dob}' read as day {day}, month {month}. The portal wants ddmmyyyy, "
            "not mmddyyyy — 03/04/1990 is 3 April, not 4 March.")
    return pan.lower() + digits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--pan", required=True)
    ap.add_argument("--dob", required=True, help="ddmmyyyy, dd/mm/yyyy or dd-mm-yyyy")
    ap.add_argument("--print-password", action="store_true",
                    help="print the derived password without opening the file")
    a = ap.parse_args()

    pw = password(a.pan, a.dob)
    if a.print_password:
        print(pw)
        return 0

    src = pathlib.Path(a.pdf)
    if not src.is_file():
        raise SystemExit(f"no such file: {src}")
    data = src.read_bytes()
    if not data.startswith(b"%PDF"):
        raise SystemExit(f"{src} does not start with %PDF")
    if not is_encrypted(data):
        print(f"{safe_name(str(src))} is not encrypted. Read it directly:\n"
              f"    python3 parse_tax_docs.py {safe_name(str(src))}")
        return 0

    try:
        dec = make_decryptor(data, pw)
    except CryptError as e:
        print(str(e), file=sys.stderr)
        return 2

    print(f"{safe_name(str(src))} opens with the derived password, "
          f"as the {dec.opened_with}.")
    print(f"  security handler: /V {dec.v} /R {dec.r}, {dec.cfm}, "
          f"{len(dec.key) * 8}-bit key")
    print("\nNothing was written. Pipe the password into the readers, which "
          "decrypt in memory — it never reaches argv, where any other process "
          "on this machine could read it out of `ps`:\n"
          f"    python3 open_ais.py {safe_name(str(src))} --pan ... --dob ... "
          "--print-password \\\n"
          f"        | python3 parse_tax_docs.py {safe_name(str(src))} "
          "--password-stdin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
