#!/usr/bin/env python3
"""Refuse to ship anything that looks like real Indian tax identifiers.

Every file in the repository is scanned, not a hand-listed set of globs. An
earlier version globbed `skills/**` and the top-level markdown, which meant
`docs/` was never looked at — and `docs/` is where the write-ups full of real
observations live.

Committed PDFs and workbooks are opened with the project's own readers and the
extracted text is scanned too. A PAN inside a fixture PDF is exactly as public
as one in a markdown file, and grepping the raw bytes of a compressed PDF finds
nothing at all.
"""
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "itr-filing-copilot", "scripts")
sys.path.insert(0, SCRIPTS)

PATTERNS = {
    "PAN":     r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
    "TAN":     r"\b[A-Z]{4}[0-9]{5}[A-Z]\b",
    "GSTIN":   r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}\b",
    "Aadhaar": r"\b[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\b",
    "IFSC":    r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
    "ack/CIN": r"\b[0-9]{15,18}[A-Z]{0,4}\b",
    # The portal password: a lowercase PAN with a date of birth as ddmmyyyy
    # appended. It is a credential whatever it opens, and a secret scanner is
    # right to flag one written out in full. Four of these were in the tree —
    # in a docstring, a fixture generator, the test suite and this file — and
    # every one is now derived from its parts instead.
    "portal password": r"\b[a-z]{5}[0-9]{4}[a-z][0-9]{8}\b",
}

# An account number is only digits, so it cannot be recognised on its own
# without flagging every amount in the repository. It is recognised by the
# company it keeps: a run of 9 to 18 digits within 40 characters of a word that
# introduces one.
ACCOUNT = re.compile(
    r"(a/?c\.?\s*(?:no\.?|number)?|account\s*(?:no\.?|number)|acct)"
    r"[^0-9\n]{0,40}([0-9]{9,18})", re.I)

# Documented placeholders and structural strings that must stay. Every entry is
# here because a fixture or a worked example needs it; nothing is added to
# silence a finding. Unused entries are reported so the list cannot rot into a
# blanket exemption.
ALLOW = {
    # the spec's own example PAN, used throughout the documentation
    "ABCDE1234F", "AAAAA0000A",
    # invented TANs in the portal-JSON and AIS fixtures
    "AAAA00000A", "BBBB11111B", "CCCC22222C", "DDDD33333D", "EEEE44444E",
    # invented branch codes in the bank-statement and portal-JSON fixtures
    "HDFC0000123", "KKBK0000123", "DCBL0000123",
    # RFC 6229 RC4 test key, which is 16 digits and so looks like an ack number
    "0102030405060708",
    # invented acknowledgement numbers in redact.py's own worked examples,
    # which exist to show what the masking does to one
    "100000000000001", "100000000000002",
}

# Raster contents cannot be inspected by this script. A person must review each
# image, record exactly what they checked, and bind that review to the file's
# bytes. New and edited images fail closed; stale entries fail too, so this can
# never become a list of filenames that everybody assumes somebody reviewed.
REVIEWED_IMAGES: dict[str, tuple[str, str]] = {}

SKIP_DIRS = {".git", "__pycache__", ".github/workflows/node_modules", "node_modules"}
TEXT_EXTS = {".md", ".txt", ".json", ".py", ".csv", ".yml", ".yaml", ".html",
             ".xml", ".cfg", ".toml", ".ini", ""}
PDF_EXTS = {".pdf"}
TABULAR_EXTS = {".xlsx", ".xls", ".xlsm"}
RASTER_EXTS = {".png", ".apng", ".jpg", ".jpeg", ".jfif", ".gif", ".webp",
               ".bmp", ".tif", ".tiff", ".ico", ".avif", ".heic", ".heif"}
BINARY_EXTS = {".zip", ".woff", ".woff2"}

# The password the encrypted fixtures use, derived rather than pasted: see
# evals/fixtures/build_encrypted_pdfs.py. A complete password written out as a
# literal is a credential-shaped string wherever it appears.
sys.path.insert(0, SCRIPTS)
from open_ais import password as _derive_password  # noqa: E402

FIXTURE_PASSWORD = _derive_password("ABCDE1234F", "01/01/1990")


def sources():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def reviewed_image_problems(paths, root=ROOT, reviewed=REVIEWED_IMAGES) -> list[str]:
    """Return every missing, changed, invalid or stale raster review entry."""
    problems = []
    found = {}
    for path in paths:
        if os.path.splitext(path)[1].lower() not in RASTER_EXTS:
            continue
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        found[rel] = path
        entry = reviewed.get(rel)
        if entry is None:
            problems.append(f"{rel}: raster file has no REVIEWED_IMAGES entry")
            continue
        if not isinstance(entry, tuple) or len(entry) != 2:
            problems.append(f"{rel}: REVIEWED_IMAGES entry must be (sha256, note)")
            continue
        expected, note = entry
        if not isinstance(note, str) or not note.strip():
            problems.append(f"{rel}: REVIEWED_IMAGES note is empty")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            problems.append(f"{rel}: REVIEWED_IMAGES SHA-256 is not 64 lowercase hex digits")
            continue
        try:
            with open(path, "rb") as fh:
                actual = hashlib.sha256(fh.read()).hexdigest()
        except OSError as e:
            problems.append(f"{rel}: image could not be hashed: {e}")
            continue
        if actual != expected:
            problems.append(
                f"{rel}: image SHA-256 changed; re-review the image and update its entry")

    for rel in sorted(set(reviewed) - set(found)):
        problems.append(
            f"REVIEWED_IMAGES entry for {rel} is stale; the file does not exist")
    return problems


# Printable ASCII a raw-stream fallback must yield before the file counts as
# scanned. Every identifier this guard matches is ASCII, so below this there is
# nothing it could have found and the file has to be reported instead.
MIN_SCANNABLE_ASCII = 200


def raw_pdf_streams(path: str) -> str | None:
    """Every decodable stream in a PDF, as text, without laying pages out.

    The last resort for a file the page reader will not interpret. Returns None
    when the file is encrypted beyond the fixture password, which is the one
    case where there is genuinely nothing to look at."""
    try:
        import read_pdf as reader
        from pdf_crypt import is_encrypted, make_decryptor
    except ImportError:
        return None
    with open(path, "rb") as fh:
        data = fh.read()
    if data.startswith(reader.JAVA_STREAM_MAGIC):
        try:
            data = reader._unwrap_java_pdf_envelope(data, os.path.basename(path))
        except Exception:                                # noqa: BLE001
            return None
    dec = None
    if is_encrypted(data):
        for password in (FIXTURE_PASSWORD, ""):
            try:
                dec = make_decryptor(data, password)
                break
            except Exception:                            # noqa: BLE001
                continue
        if dec is None:
            return None
    try:
        objects, gens = reader._objects(data)
        reader._expand_object_streams(objects, gens, dec)
    except Exception:                                    # noqa: BLE001
        return None
    out = []
    for num, body in objects.items():
        try:
            piece = reader._stream_bytes(body, objects, num, gens.get(num, 0), dec)
        except Exception:                                # noqa: BLE001
            continue
        if piece:
            out.append(piece.decode("latin-1", "replace"))
        out.append(body.decode("latin-1", "replace"))
    if not out:
        return None
    text = "\n".join(out)
    # Fail closed. A stream that stayed compressed decodes to bytes that carry
    # no readable runs, and returning those would mark the file scanned while
    # anything inside it stayed hidden. An identifier this guard looks for is
    # ASCII, so a file with no ASCII runs has not been scanned.
    runs = re.findall(r"[ -~]{4,}", text)
    if sum(len(r) for r in runs) < MIN_SCANNABLE_ASCII:
        return None
    return text


def text_of(path: str, unreadable: list) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    rel = os.path.relpath(path, ROOT)
    if ext in RASTER_EXTS or ext in BINARY_EXTS:
        return None
    if ext in PDF_EXTS:
        try:
            from read_pdf import PdfError, extract_pages
        except ImportError:
            unreadable.append(f"{rel}: the PDF reader could not be imported")
            return None
        for password in (None, FIXTURE_PASSWORD):
            try:
                return "\n".join(extract_pages(path, password))
            except PdfError:
                continue
            except Exception as e:                       # noqa: BLE001
                unreadable.append(f"{rel}: {type(e).__name__}: {e}")
                return None
        # extract_pages refuses for reasons that have nothing to do with what
        # the bytes contain — a cyclic Form graph, glyphs it cannot map, a page
        # it cannot lay out. A refusal to *interpret* is not permission to leave
        # a file unscanned, so fall back to the decoded content streams. Reading
        # them raw is worse text and a strictly wider net, which is what this
        # guard wants.
        raw = raw_pdf_streams(path)
        if raw is not None:
            return raw
        unreadable.append(
            f"{rel}: the page reader refused it and its streams did not decode "
            "to anything scannable")
        return None
    if ext in TABULAR_EXTS:
        try:
            from read_tabular import load_sheets
        except ImportError:
            unreadable.append(f"{rel}: the workbook reader could not be imported")
            return None
        try:
            sheets = load_sheets(path)
        except Exception as e:                           # noqa: BLE001
            unreadable.append(f"{rel}: {type(e).__name__}: {e}")
            return None
        return "\n".join(" ".join(str(c) for c in row)
                         for rows in sheets.values() for row in rows)
    if ext in TEXT_EXTS:
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except (OSError, UnicodeDecodeError):
            unreadable.append(f"{rel}: not readable as UTF-8 text")
            return None
    return None


def main() -> int:
    hits, unreadable, used = [], [], set()
    scanned = 0
    paths = list(sources())
    image_problems = reviewed_image_problems(paths)

    for path in paths:
        content = text_of(path, unreadable)
        if content is None:
            continue
        scanned += 1
        rel = os.path.relpath(path, ROOT)
        for lineno, line in enumerate(content.splitlines(), 1):
            for label, pattern in PATTERNS.items():
                for match in re.findall(pattern, line):
                    value = match if isinstance(match, str) else match[0]
                    if value.replace(" ", "") in ALLOW:
                        used.add(value.replace(" ", ""))
                        continue
                    hits.append(f"{rel}:{lineno}  {label}: {value}")
            for _, digits in ACCOUNT.findall(line):
                if digits in ALLOW:
                    used.add(digits)
                    continue
                hits.append(f"{rel}:{lineno}  account number: {digits}")

    if unreadable:
        print("Files that could not be read, and so could not be scanned:")
        for item in unreadable:
            print("  ", item)
        print("A file nobody can scan is not a file nobody can read. Convert it, "
              "or delete it.\n")

    if image_problems:
        print("Raster files that do not have a current human review:")
        for problem in image_problems:
            print("  ", problem)
        print("Add an exact path, SHA-256 and review note to REVIEWED_IMAGES only "
              "after a person has inspected the pixels.\n")

    if hits:
        print("Possible real tax identifiers — review before shipping:")
        for hit in sorted(set(hits)):
            print("  ", hit)
        print("\nIf one of these is a deliberate placeholder, add it to ALLOW in "
              "this file with a comment saying which fixture needs it. Do not "
              "widen a pattern to make a finding go away.")
    if hits or unreadable or image_problems:
        return 1

    stale = ALLOW - used
    print(f"No tax identifiers found across {scanned} files.")
    if stale:
        print("\nALLOW entries that nothing uses any more — delete them, an "
              "exemption nobody needs is an exemption nobody reviews:")
        for value in sorted(stale):
            print("   ", value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
