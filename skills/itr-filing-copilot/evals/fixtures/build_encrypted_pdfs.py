#!/usr/bin/env python3
"""
Rebuild the encrypted-PDF fixtures. Run this only to regenerate them.

    pip install pikepdf
    python3 build_encrypted_pdfs.py

This is the one script in the project that takes a dependency, and it is
deliberately not part of the test run. `pdf_crypt.py` implements the PDF
standard security handler from the specification; a test that encrypted a file
with `pdf_crypt` and then decrypted it with `pdf_crypt` would agree with itself
however wrong it was. So the fixtures are written by **pikepdf**, which wraps
qpdf, and the test suite decrypts them with the standard library alone. That
makes `test_parsers.py` a cross-validation against an independent
implementation rather than a round trip.

The content is invented. There is no PAN, no account number and no figure taken
from anybody's return — the two sentences exist so a decryption that half-works
is visibly different from one that works. The amounts are deliberately
meaningless: an early draft of this file reused two real interest figures from
the reconciliation notes, which is exactly the leak the PII scanner exists to
stop and exactly the sort it would not have caught.

Coverage
--------
    /V 1 /R 2   RC4, 40-bit          — what AIS and TIS actually use
    /V 2 /R 3   RC4, 128-bit         — what Form 16 and the s.143(1) intimation use
    /V 4 /R 4   AES-128 (/AESV2)     — newer portal and payroll output
    /V 5 /R 6   AES-256 (/AESV3)     — PDF 2.0

Both a user-password file and an empty-user-password file are written for R2,
because an encrypted PDF that opens with no password at all is a case worth
keeping: it must not prompt for one.

Two more fixtures cover a different axis entirely: **object streams**. From PDF
1.5 on a writer may pack page and font dictionaries into a compressed
`/Type /ObjStm` container with a cross-reference stream, leaving nothing in the
file that looks like `N 0 obj`. A reader that only scans for that pattern finds
no pages at all, and this one did — every other fixture here is PDF 1.3 or 1.4,
so nothing caught it. One plain and one AES-128 encrypted, because the container
is encrypted and the objects inside it are not.

Revision 5 is not covered. It was a deprecated Adobe extension, qpdf will not
write it, and no file using it has been seen. `pdf_crypt` implements it from
the specification and it stays `[UNVERIFIED]` until a real one turns up.
"""
import os
import sys

# Derived with the product's own function rather than pasted as a literal: a
# complete password written out in a source file is a credential-shaped string
# whether or not it opens anything real, and secret scanners are right to say so.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "scripts"))
from open_ais import password as _derive_password  # noqa: E402

PLACEHOLDER_PAN = "ABCDE1234F"      # the specification's own example PAN
PLACEHOLDER_DOB = "01/01/1990"

PLAIN = "plain_synthetic.pdf"
PAGE_ONE = "Page one of an invented statement, amount 1111.11"
PAGE_TWO = "Page two of an invented statement, amount 2222.22"
USER_PW = _derive_password(PLACEHOLDER_PAN, PLACEHOLDER_DOB)
OWNER_PW = "ownerpw"

VARIANTS = [
    ("r2_rc4_40", dict(R=2, aes=False, metadata=False), (USER_PW, "")),
    ("r3_rc4_128", dict(R=3, aes=False, metadata=False), (USER_PW,)),
    ("r4_aes_128", dict(R=4, aes=True, metadata=True), (USER_PW,)),
    ("r6_aes_256", dict(R=6, aes=True, metadata=True), (USER_PW,)),
]


def base_pdf(path: str) -> None:
    """A two-page PDF with a text layer, written by hand so the baseline is
    not itself produced by the library under test."""
    def content(text: str) -> bytes:
        return b"BT /F1 12 Tf 72 720 Td (" + text.encode() + b") Tj ET\n"

    s1, s2 = content(PAGE_ONE), content(PAGE_TWO)
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Count 2 /Kids [3 0 R 4 0 R] >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
           b"<< /Font << /F1 7 0 R >> >> /Contents 5 0 R >>",
        4: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
           b"<< /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
        5: b"<< /Length %d >>\nstream\n" % len(s1) + s1 + b"\nendstream",
        6: b"<< /Length %d >>\nstream\n" % len(s2) + s2 + b"\nendstream",
        7: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
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
    out += (b"trailer\n<< /Size %d /Root 1 0 R /ID "
            b"[<0102030405060708090a0b0c0d0e0f10> "
            b"<0102030405060708090a0b0c0d0e0f10>] >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref))
    with open(path, "wb") as fh:
        fh.write(bytes(out))


def main() -> int:
    try:
        import pikepdf
    except ImportError:
        print("this generator needs pikepdf:  pip install pikepdf\n"
              "Nothing else in the project does. The fixtures it writes are "
              "already committed; you only need it to rebuild them.",
              file=sys.stderr)
        return 2

    base_pdf(PLAIN)
    written = [PLAIN]
    for name, kw, user_passwords in VARIANTS:
        for user in user_passwords:
            label = "user" if user else "empty"
            out = f"encrypted_{name}_{label}_synthetic.pdf"
            with pikepdf.open(PLAIN) as pdf:
                pdf.save(out, encryption=pikepdf.Encryption(
                    owner=OWNER_PW, user=user, **kw))
            written.append(out)
    # Object streams: what any PDF 1.5+ writer emits, encrypted and not.
    for name, kw in (("objstm_synthetic.pdf", {}),
                     ("encrypted_r4_aes_128_objstm_synthetic.pdf",
                      {"encryption": pikepdf.Encryption(
                          owner=OWNER_PW, user=USER_PW, R=4, aes=True,
                          metadata=True)})):
        with pikepdf.open(PLAIN) as pdf:
            pdf.save(name,
                     object_stream_mode=pikepdf.ObjectStreamMode.generate, **kw)
        written.append(name)

    print(f"wrote {len(written)} fixture(s) with pikepdf {pikepdf.__version__}:")
    for f in written:
        print("   ", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
