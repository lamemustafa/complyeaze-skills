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
from pdf_crypt import (CryptError, is_encrypted,  # noqa: E402
                       make_decryptor, resolve_password)  # noqa: E402
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
    ap.add_argument("--pan")
    ap.add_argument("--dob", help="ddmmyyyy, dd/mm/yyyy or dd-mm-yyyy")
    # The whole point of this script is to settle a credential without running
    # any text gate. Deriving PAN+DOB is the common case; an employer Form 16
    # password is set by payroll and need not be that pair at all.
    # `[observed 2026-07-31, one employer Form 16]` That one opened on the PAN
    # in upper case with no date. One document does not establish how often, so
    # no frequency is claimed here — what matters is that the case exists and
    # this was the one script that could not test it, while the reference file
    # told readers to use it for exactly that.
    ap.add_argument("--password", help="test this password instead of deriving "
                                       "one from --pan and --dob")
    ap.add_argument("--password-stdin", action="store_true",
                    help="read the password from standard input instead, so it "
                         "never appears in argv or in shell history")
    ap.add_argument("--print-password", action="store_true",
                    help="print the derived password without opening the file")
    a = ap.parse_args()

    # An empty user password is a real PDF case, and the committed
    # encrypted_r2_rc4_40_empty_synthetic.pdf fixture is exactly that. A
    # truthiness test would send `--password ''` down the derive branch and
    # refuse a credential the file actually opens with.
    if a.password is not None or a.password_stdin:
        if a.pan or a.dob:
            raise SystemExit(
                "--password / --password-stdin and --pan / --dob are two ways "
                "to supply one credential. Pass one.")
        if a.print_password:
            raise SystemExit(
                "--print-password prints a DERIVED password; there is nothing "
                "to derive when the password is supplied.")
        if a.password is not None and a.password_stdin:
            # resolve_password() picks between the two by truthiness, so an
            # empty --password loses to --password-stdin silently — and an
            # empty password is exactly the case this branch exists to accept.
            # Two sources is a caller error either way; say so rather than
            # validating whichever one happened to win.
            raise SystemExit(
                "--password and --password-stdin are two sources for one "
                "credential. Pass one.")
        try:
            pw = resolve_password(a.password, a.password_stdin)
        except CryptError as e:
            raise SystemExit(str(e))
        source = "supplied password"
    else:
        if not (a.pan and a.dob):
            raise SystemExit(
                "supply the credential: --pan and --dob to derive the "
                "department's rule, or --password / --password-stdin to test "
                "one you already have. [observed 2026-07-31, one employer "
                "Form 16] A payroll-issued password need not be PAN and date "
                "of birth at all; that one opened on the PAN in upper case "
                "with no date.")
        pw = password(a.pan, a.dob)
        source = "derived password"
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

    print(f"{safe_name(str(src))} opens with the {source}, "
          f"as the {dec.opened_with}.")
    print(f"  security handler: /V {dec.v} /R {dec.r}, {dec.cfm}, "
          f"{len(dec.key) * 8}-bit key")
    print("\nNothing was written. Pipe the password into the readers, which "
          "decrypt in memory — it never reaches argv, where any other process "
          "on this machine could read it out of `ps`:")
    if source == "supplied password":
        # Sending the reader off to derive PAN+DOB here would hand it a
        # different credential from the one just confirmed, and for a payroll
        # password that is precisely the one that does not work.
        # Angle brackets are redirections in a shell, so a `<placeholder>` is a
        # syntax error rather than a prompt. This line is meant to be pasted.
        print(f"    your-password-source | python3 parse_tax_docs.py "
              f"{safe_name(str(src))} --password-stdin")
        print("      (replace your-password-source with whatever prints the "
              "password — a secrets manager, `pass`, or `printf` for an empty "
              "one)")
    else:
        print(f"    python3 open_ais.py {safe_name(str(src))} --pan ... "
              "--dob ... --print-password \\\n"
              f"        | python3 parse_tax_docs.py {safe_name(str(src))} "
              "--password-stdin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
