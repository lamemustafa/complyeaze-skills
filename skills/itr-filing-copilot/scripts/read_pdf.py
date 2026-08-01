#!/usr/bin/env python3
"""
Minimal PDF text extractor that keeps the layout. Standard library only.

    from read_pdf import extract_pages
    pages = extract_pages("AIS.pdf")      # ["page 1 text", "page 2 text", ...]

    python3 read_pdf.py AIS.pdf           # print it
    python3 read_pdf.py AIS.pdf --page 3

Why this exists
---------------
Every document that anchors an Indian return arrives as a PDF: AIS, TIS,
Form 26AS, Form 168, Form 16, bank statements, the s.143(1) intimation. The
usual answers are pdfplumber or pypdf, and asking a taxpayer to pip-install a
C-extension before they can read their own tax statement loses more people than
it helps. A PDF content stream is zlib-compressed PostScript-like operators, and
zlib is in the standard library.

What it does and does not do
----------------------------
It reads text drawn with the ordinary text operators, decodes it through the
font's /ToUnicode map where one exists, and lays each page out on a character
grid using the text matrix, so columns stay in columns. That is what makes a
table readable line by line.

[observed 2026-07-30] Some portal downloads with a ``.pdf`` name are a
Java-serialized ``Object[]`` carrying the PDF in a length-prefixed ``byte[]``.
Those are unwrapped from the declared byte length before PDF parsing begins.

[observed 2026-07-31] A page's text is not always in its ``/Contents``. One real
Form 16 drew a page-number footer there and invoked a Form XObject holding the
whole certificate, so reading ``/Contents`` alone recovered ``1of9`` from nine
pages and the document was then refused. Form XObjects are followed through
``Do``, inlined where they are invoked so the surrounding graphics state and
their own ``/Matrix`` apply, with each scope's font names kept distinct, a
visited set so a cycle terminates, and a depth cap whose breach is reported as
loss rather than silently truncating the page.

It does not do OCR. A scanned statement has no text layer and comes back empty,
which the caller must treat as "unreadable", never as "no transactions".
Anything it cannot decode is dropped rather than guessed at, so a caller that
reconciles totals will notice.

Encrypted files open in place. AIS, TIS, the s.143(1) intimation and most
Form 16s are password-protected with the taxpayer's own PAN and date of birth;
`pdf_crypt.py` implements the standard security handler so `--password` is all
that is needed and no decrypted copy is ever written to disk.
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdf_crypt import (CryptError, is_encrypted,  # noqa: E402
                       make_decryptor, resolve_password)
from redact import safe_name  # noqa: E402

# Content-stream tokens we care about. Everything else is skipped.
TOKEN = re.compile(rb"""
    (?P<str>\((?:\\.|[^()\\])*\))      # (literal string)
  | (?P<hex><[0-9A-Fa-f\s]*>)          # <hex string>
  | (?P<num>[-+]?\d*\.?\d+)
  | (?P<name>/[^\s/\[\]<>(){}]+)
  | (?P<arr>[\[\]])
  | (?P<op>[A-Za-z'"*]+)
""", re.X)

ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
           b"(": b"(", b")": b")", b"\\": b"\\"}

COMBINING_MARK_CATEGORIES = frozenset({"Mn", "Mc", "Me"})
JOIN_CONTROLS = frozenset({"\u200c", "\u200d"})
TEXT_SHOWING_OPERATORS = frozenset({b"Tj", b"TJ", b"'", b'"'})
JAVA_STREAM_MAGIC = b"\xac\xed\x00\x05"
JAVA_BYTE_ARRAY_DESCRIPTOR = (
    b"\x75\x72\x00\x02[B\xac\xf3\x17\xf8\x06\x08\x54\xe0"
    b"\x02\x00\x00\x78\x70"
)
# Word tokens per 1,000 characters that carry ink — see _has_plausible_word_density
# for why the denominator excludes the layout padding this reader adds itself.
# [observed 2026-07-31] Of the 21 committed PDFs in evals/fixtures, the 20 that
# are meant to be read have a minimum density of 80.4 three-character word
# tokens per 1,000 ink characters. Measured the old way, against the whole
# laid-out string, that same minimum was 8.0 — the difference is the padding.
# The twenty-first, xobject_cycle_synthetic.pdf, is refused by design.
# [observed 2026-07-29] The reported 81-page ITR-3 reproduction measured 0.0.
# [observed 2026-07-31] A real 82-page bank statement that reads perfectly
# measured 1.42 the old way and 57.09 this way; it was being refused.
# [inferred] Five leaves 16x headroom below the weakest fixture. Numeric-heavy
# tables still carry headings; measuring the whole document lets a blank, cover,
# or unusually sparse page coexist with readable pages instead of being refused.
MIN_WORD_TOKENS_PER_1000_CHARS = 5

# How far to follow Form XObjects invoking Form XObjects.
# [observed 2026-07-31, one real employer-issued Form 16] That document nests
# one level. [inferred] Two or three levels is unremarkable for a page composed
# from reusable parts, and eight leaves room above anything seen. [UNVERIFIED]
# No document has been observed nesting deeper than one, so the cap is a
# backstop rather than a measured limit; exceeding it is reported as loss.
MAX_FORM_XOBJECT_DEPTH = 8

# Total bytes a page's Form expansion may produce. Depth and the cycle check
# bound recursion but not fan-out: nine Forms each invoking the next ten times
# is acyclic, eight deep, and materialises on the order of a hundred million
# leaf copies. A compact file must refuse, not exhaust the machine.
MAX_FORM_EXPANSION_BYTES = 8 * 1024 * 1024

# How far to climb /Parent looking for inherited /Resources. The page tree is
# shallow in practice; this only bounds a malformed or self-referential one.
MAX_PAGE_TREE_DEPTH = 32

# Of every letter extracted, the share that must belong to a word of at least
# two letters. Catches a page that decoded one heading and reduced the rest to
# isolated glyphs, which the density floor alone accepts. Digits are excluded
# from both sides, so a numeric table is not penalised for being numeric.
# [observed 2026-07-31, recomputed against the two-character tokenizer] The
# committed fixtures measure 98.2% at the lowest and the real 82-page
# statement 80.8%; isolated-glyph noise measures 0% to 22%. Forty sits about
# twice below the weakest real document and roughly twice above the strongest
# noise. A page of legitimate single-letter labels would score low, which this
# cannot tell from unmapped output — a real limit, recorded not papered over.
MIN_LETTERS_IN_WORDS_PCT = 40

# A sparse page whose few letters form words already scores 100%, so the
# minimum only avoids judging a page too small to measure at all — a divider
# carrying two stray characters.
MIN_LETTERS_TO_JUDGE_PAGE = 6


class PdfError(Exception):
    """The file is not a PDF this reader can decode."""


def _word_tokens(text: str, minimum: int = 3) -> list[str]:
    """Return words made of Unicode letters and their combining marks.

    `minimum` counts characters, marks included: an Indic word may carry only
    two base letters under five characters, and measuring it by base letters
    alone drops it."""
    words: list[str] = []
    current: list[str] = []
    for index, char in enumerate(text):
        is_word_char = (char.isalpha()
                        or unicodedata.category(char)
                        in COMBINING_MARK_CATEGORIES)
        # [inferred] Admit only ZWNJ and ZWJ, and only when they actually join
        # adjacent letters or marks. The broader Cf category also contains soft
        # hyphen and directional overrides, whose presence inside a word is not
        # obviously benign and must not silently raise the density score.
        is_joining = (
            char in JOIN_CONTROLS
            and 0 < index < len(text) - 1
            and (text[index - 1].isalpha()
                 or unicodedata.category(text[index - 1])
                 in COMBINING_MARK_CATEGORIES)
            and (text[index + 1].isalpha()
                 or unicodedata.category(text[index + 1])
                 in COMBINING_MARK_CATEGORIES)
        )
        if is_word_char or is_joining:
            current.append(char)
            continue
        if len(current) >= minimum:
            words.append("".join(current))
        current = []
    if len(current) >= minimum:
        words.append("".join(current))
    return words


def _java_take(data: bytes, offset: int, size: int, what: str) -> tuple[bytes, int]:
    end = offset + size
    if end > len(data):
        raise ValueError(f"ended while reading {what}")
    return data[offset:end], end


def _java_utf(data: bytes, offset: int, what: str) -> tuple[str, int]:
    raw_length, offset = _java_take(data, offset, 2, f"{what} length")
    raw, offset = _java_take(
        data, offset, int.from_bytes(raw_length, "big"), what)
    try:
        return raw.decode("ascii"), offset
    except UnicodeDecodeError:
        raise ValueError(f"{what} is not an ASCII class or field name") from None


def _java_class_desc(
        data: bytes, offset: int, what: str
) -> tuple[str, int, int, list[tuple[bytes, str]], int]:
    token, offset = _java_take(data, offset, 1, f"{what} token")
    if token != b"\x72":
        raise ValueError(f"{what} is not a class descriptor")
    class_name, offset = _java_utf(data, offset, f"{what} name")
    uid, offset = _java_take(data, offset, 8, f"{what} serial UID")
    flags, offset = _java_take(data, offset, 1, f"{what} flags")
    raw_count, offset = _java_take(data, offset, 2, f"{what} field count")
    fields = []
    for index in range(int.from_bytes(raw_count, "big")):
        type_code, offset = _java_take(
            data, offset, 1, f"{what} field {index + 1} type")
        field_name, offset = _java_utf(
            data, offset, f"{what} field {index + 1} name")
        if type_code in (b"L", b"["):
            raise ValueError(f"{what} has an unsupported object field")
        fields.append((type_code, field_name))
    ending, offset = _java_take(data, offset, 2, f"{what} ending")
    if ending != b"\x78\x70":
        raise ValueError(f"{what} has annotations or a superclass")
    return class_name, int.from_bytes(uid, "big"), flags[0], fields, offset


def _unwrap_java_pdf_envelope(data: bytes, name: str) -> bytes:
    """Extract the authoritative byte[] from the observed portal envelope."""
    try:
        offset = len(JAVA_STREAM_MAGIC)
        token, offset = _java_take(data, offset, 1, "Object[] token")
        if token != b"\x75":
            raise ValueError("root object is not an array")
        array_name, uid, flags, fields, offset = _java_class_desc(
            data, offset, "Object[]")
        if (array_name != "[Ljava.lang.Object;"
                or uid != 0x90CE589F1073296C or flags != 0x02 or fields):
            raise ValueError("root array is not the observed Object[] type")
        raw_count, offset = _java_take(data, offset, 4, "Object[] length")
        if int.from_bytes(raw_count, "big") != 2:
            raise ValueError("root Object[] does not contain two elements")
        token, offset = _java_take(data, offset, 1, "header-map token")
        if token != b"\x73":
            raise ValueError("first Object[] element is not an object")
        map_name, uid, flags, fields, offset = _java_class_desc(
            data, offset, "header map")
        if (map_name != "java.util.HashMap"
                or uid != 0x0507DAC1C31660D1 or flags != 0x03
                or fields != [(b"F", "loadFactor"), (b"I", "threshold")]):
            raise ValueError("first Object[] element is not the observed HashMap")
        _, offset = _java_take(data, offset, 8, "HashMap fields")
    except ValueError as exc:
        raise PdfError(
            f"{name}: malformed Java-serialized PDF envelope ({exc}).") from None

    # Walk forward to the serialized byte[] class descriptor. We never hunt for
    # %PDF or %%EOF: a candidate is valid only when its declared byte length
    # consumes the file exactly, so that length remains authoritative.
    candidates = []
    mismatches = []
    search_from = offset
    while True:
        start = data.find(JAVA_BYTE_ARRAY_DESCRIPTOR, search_from)
        if start < 0:
            break
        length_offset = start + len(JAVA_BYTE_ARRAY_DESCRIPTOR)
        if start > offset and data[start - 1:start] == b"\x78" \
                and length_offset + 4 <= len(data):
            declared = int.from_bytes(data[length_offset:length_offset + 4], "big")
            payload_start = length_offset + 4
            remaining = len(data) - payload_start
            if declared == remaining:
                candidates.append(data[payload_start:payload_start + declared])
            else:
                mismatches.append((declared, remaining))
        search_from = start + 1
    if len(candidates) == 1:
        return candidates[0]
    if mismatches and not candidates:
        declared, remaining = mismatches[-1]
        raise PdfError(
            f"{name}: malformed Java-serialized PDF envelope (declared "
            f"byte-array length {declared}, but {remaining} bytes remain).")
    detail = ("more than one complete byte-array payload"
              if candidates else "no complete byte-array payload")
    raise PdfError(
        f"{name}: malformed Java-serialized PDF envelope ({detail}).")


def _letters_in_words_share(text: str) -> float:
    """Percentage of extracted letters that belong to a word of three or more.

    Both sides count only `isalpha()` characters. `_word_tokens` also admits
    combining marks and the ZWJ/ZWNJ joiners, so measuring a token by its length
    would credit characters the denominator never counted — one `abc` among
    fifteen combining marks and twenty isolated letters would score as readable.
    Returns 0.0 for text with no letters at all, which the caller treats
    separately: a page of pure digits is not glyph noise."""
    letters = sum(1 for char in text if char.isalpha())
    if not letters:
        return 0.0
    # Two letters or more, not the three used for density. A correctly decoded
    # ledger is full of legitimate two-letter labels — No, Dt, Cr, Dr, By, To —
    # and judging those as noise refuses a page that decoded perfectly. Unmapped
    # output is isolated *single* glyphs, which this still scores at zero.
    #
    # Tokenised the same way as the density words rather than by a regex on word
    # characters: a Devanagari or Tamil matra is a combining mark, and a class
    # built from \w excludes it, so an Indic word was split at every mark and
    # its letters went uncounted while the denominator still counted them.
    in_runs = sum(1 for run in _word_tokens(text, minimum=2)
                  for char in run if char.isalpha())
    return in_runs * 100.0 / letters


def _page_is_glyph_noise(text: str) -> bool:
    """Whether one page decoded a little text and lost the rest to glyphs.

    Aggregating first lets a readable page dilute a corrupted one: a document
    whose second page decoded a heading and reduced its body to isolated glyphs
    passed the document gate on the strength of the first page, and the
    per-page gate accepted it too because the heading forms a word. A caller
    then receives an incomplete statement as a complete one.

    Judged only once a page carries enough letters to measure. Below that a
    page is legitimately sparse — a cover, a divider, a page of pure figures —
    and the document-level gate is the right place to weigh it."""
    letters = sum(1 for char in text if char.isalpha())
    if letters < MIN_LETTERS_TO_JUDGE_PAGE:
        return False
    return _letters_in_words_share(text) < MIN_LETTERS_IN_WORDS_PCT


def _has_plausible_word_density(pages: list[str]) -> bool:
    """Whether document-level extraction contains a plausible number of words.

    Measured against characters that carry ink, not against the length of the
    laid-out string. `_page_text` pads every page out to a character grid so
    columns line up, so the string is mostly spaces this function put there —
    and dividing by it means a page is judged less readable the wider it is
    drawn. That is a property of the reader's own formatting, not of the
    document.

    [observed 2026-07-31] A real 82-page bank statement was refused as
    unreadable on this test. It extracted cleanly: 1,928,950 characters of which
    only 48,085 carried ink, and 2,745 words. Against the whole string the ratio
    was 1.42 and it failed a threshold of 5; against ink it is 57.09.
    [inferred] Any wide, sparse, multi-column document trends the same way as
    its page grows, which would include Form 26AS and broker reports; only the
    bank statement was observed.
    A density floor alone accepts a page that decoded one heading and turned the
    rest into isolated glyphs: one token among thirty ink characters clears five
    per thousand. So the letters are checked too — of every letter extracted,
    what share belongs to a word of at least three. Isolated glyph noise scores
    near zero however tightly it is packed, and a real document scores high even
    when it is mostly numeric, because digits are not letters and never enter
    this ratio. [observed 2026-07-31] Across the committed fixtures and one real
    82-page statement the range is 78% to 96%; glyph noise measures 0% to 13%.
    Forty sits about twice below the weakest real document and twice above the
    strongest noise."""
    text = "\n".join(pages)
    ink = sum(1 for char in text if not char.isspace())
    if not ink:
        return False
    words = _word_tokens(text)
    if len(words) * 1000 < MIN_WORD_TOKENS_PER_1000_CHARS * ink:
        return False
    return _letters_in_words_share(text) >= MIN_LETTERS_IN_WORDS_PCT


def _has_text_showing_operator(content: bytes) -> bool:
    return any(m.lastgroup == "op" and m.group() in TEXT_SHOWING_OPERATORS
               for m in TOKEN.finditer(content))


def _page_lost_text(content: bytes, text: str, stream_failed: bool) -> bool:
    """Whether a page attempted text extraction but lost all readable words."""
    if stream_failed:
        return True
    return ((_has_text_showing_operator(content) and not _word_tokens(text))
            or _page_is_glyph_noise(text))


def _page_loss_kind(content: bytes, text: str, stream_failed: bool) -> str | None:
    """Which way a page was lost, or None. The two are different failures."""
    if stream_failed:
        return "stream"
    if _has_text_showing_operator(content) and not _word_tokens(text):
        return "wordless"
    if _page_is_glyph_noise(text):
        return "glyphs"
    return None


def _unescape(raw: bytes) -> bytes:
    out, i = bytearray(), 0
    while i < len(raw):
        c = raw[i:i + 1]
        if c != b"\\":
            out += c
            i += 1
            continue
        nxt = raw[i + 1:i + 2]
        if nxt in ESCAPES:
            out += ESCAPES[nxt]
            i += 2
        elif nxt.isdigit():
            j = i + 1
            digits = b""
            while j < len(raw) and raw[j:j + 1].isdigit() and len(digits) < 3:
                digits += raw[j:j + 1]
                j += 1
            out += bytes([int(digits, 8) & 0xFF])
            i = j
        elif nxt == b"\n":
            i += 2
        else:
            out += nxt
            i += 2
    return bytes(out)


def _objects(data: bytes) -> tuple[dict[int, bytes], dict[int, int]]:
    """Every `N G obj ... endobj` body, by object number, with its generation.

    The cross-reference table is skipped deliberately: a scan finds objects in
    linearised, incrementally-updated and mildly corrupt files alike, and later
    definitions overwrite earlier ones, which is what an incremental update
    means anyway.

    The generation number is kept because encryption needs it: the per-object
    key in Algorithm 1 is derived from the object and generation numbers
    together, and assuming generation 0 decrypts a revised object to noise."""
    out: dict[int, bytes] = {}
    gens: dict[int, int] = {}
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", data):
        num, gen = int(m.group(1)), int(m.group(2))
        end = data.find(b"endobj", m.end())
        out[num] = data[m.end():end if end != -1 else len(data)]
        gens[num] = gen
    return out, gens


def _stream_bytes(body: bytes, objects: dict[int, bytes],
                  num: int | None = None, gen: int = 0, dec=None) -> bytes | None:
    m = re.search(rb"stream\r?\n", body)
    if not m:
        return None
    raw = body[m.end():]
    end = raw.rfind(b"endstream")
    if end != -1:
        raw = raw[:end]
    # A stream is followed by an end-of-line and then `endstream`, and that EOL
    # is not part of the data. Keeping it was harmless for Flate and for RC4 —
    # zlib ignores a trailing byte and a stream cipher does not care about
    # length — but an AES stream must be a whole number of 16-byte blocks, and
    # one stray newline made every one of them a byte over. `/Length` is
    # authoritative where it is a direct integer; otherwise trim one EOL.
    # The digit lookahead is a token boundary: without it the engine can
    # backtrack inside `12 0 R` and accept `1` as a direct length. Indirect
    # lengths are deliberately not resolved here; they fall through to the EOL
    # trim, which preserves the AES whole-block invariant below.
    declared = re.search(
        rb"/Length\s+(\d+)(?!\d)(?!\s+\d+\s+R\b)", body)
    if declared and int(declared.group(1)) <= len(raw):
        raw = raw[:int(declared.group(1))]
    elif raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n") or raw.endswith(b"\r"):
        raw = raw[:-1]
    # Decryption comes before the filters: a stream is compressed and then
    # encrypted, so it has to be decrypted and then decompressed. Cross-
    # reference streams are exempt by the spec — they are never encrypted,
    # because a reader has to find the /Encrypt dictionary through them.
    if dec is not None and num is not None and not re.search(rb"/Type\s*/XRef", body):
        raw = dec.decrypt(raw, num, gen)
    filters = re.search(rb"/Filter\s*(/\w+|\[[^\]]*\])", body)
    name = filters.group(1) if filters else b""
    if b"FlateDecode" in name:
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            try:
                raw = zlib.decompressobj().decompress(raw)
            except zlib.error:
                return None
    elif b"ASCIIHexDecode" in name:
        hexed = re.sub(rb"[^0-9A-Fa-f]", b"", raw.split(b">")[0])
        raw = bytes.fromhex(hexed.decode("ascii", "ignore")
                            [:len(hexed) // 2 * 2])
    elif name and b"Decode" in name:
        return None                      # LZW, RunLength, DCT: not text
    return raw


def _expand_object_streams(objects: dict[int, bytes], gens: dict[int, int],
                           dec) -> int:
    """Splice in the objects that live inside `/Type /ObjStm` containers.

    From PDF 1.5 on, a writer may pack most non-stream objects — page
    dictionaries, font dictionaries, the catalog — into a compressed object
    stream, leaving nothing in the file that looks like `N 0 obj`. A reader that
    only scans for that pattern finds no pages at all, which is what this one
    did: a file saved by any modern writer came back as "no readable pages".

    The container holds `/N` pairs of `objnum offset` before `/First`, then the
    objects themselves. Objects inside it are not separately encrypted — the
    container is — so decryption happens once, on the way in.

    An object found by the direct scan wins over one of the same number found
    here. In practice an object is in one place or the other, never both, and
    preferring the visible definition is the conservative way round.
    """
    added = 0
    for num in sorted(objects):
        body = objects[num]
        if not re.search(rb"/Type\s*/ObjStm", body):
            continue
        raw = _stream_bytes(body, objects, num, gens.get(num, 0), dec)
        if raw is None:
            raise PdfError(f"object stream {num} could not be decoded")
        count = re.search(rb"/N\s+(\d+)", body)
        first = re.search(rb"/First\s+(\d+)", body)
        if not count:
            raise PdfError(f"object stream {num} has no /N entry")
        if not first:
            raise PdfError(f"object stream {num} has no /First entry")
        n, start = int(count.group(1)), int(first.group(1))
        if start > len(raw):
            raise PdfError(
                f"object stream {num} has /First {start} beyond its "
                f"{len(raw)} decoded bytes")
        header = raw[:start].split()
        if len(header) < 2 * n:
            raise PdfError(
                f"object stream {num} has {len(header)} header tokens; "
                f"expected at least {2 * n} for /N {n}")
        offsets = []
        for i in range(n):
            try:
                offsets.append((int(header[2 * i]), int(header[2 * i + 1])))
            except ValueError:
                raise PdfError(
                    f"object stream {num} has a non-numeric object header")
        payload_length = len(raw) - start
        for index, (obj_num, offset) in enumerate(offsets):
            next_offset = (offsets[index + 1][1]
                           if index + 1 < len(offsets) else payload_length)
            if not 0 <= offset <= next_offset <= payload_length:
                raise PdfError(
                    f"object stream {num} has an invalid offset for object "
                    f"{obj_num}")
            if obj_num in objects:
                continue
            objects[obj_num] = raw[start + offset:start + next_offset]
            gens.setdefault(obj_num, 0)
            added += 1
    return added


def _tounicode(stream: bytes) -> dict[int, str]:
    """Parse the /ToUnicode CMap so subset-encoded fonts read as text."""
    table: dict[int, str] = {}

    def to_str(hexed: bytes) -> str:
        # A destination may hold several UTF-16 units — a ligature such as "fi"
        # is written <0066 0069>. Dropping that entry shifts every later index
        # in the array by one, which silently rewrites letters and digits
        # further down the document.
        raw = bytes.fromhex(re.sub(rb"\s+", b"", hexed).decode("ascii", "ignore"))
        try:
            return raw.decode("utf-16-be")
        except UnicodeDecodeError:
            return raw.decode("latin-1", "replace")

    for block in re.findall(rb"beginbfchar(.*?)endbfchar", stream, re.S):
        for src, dst in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f\s]+)>", block):
            table[int(src, 16)] = to_str(dst)
    # bfrange has two forms. `<lo> <hi> <dst>` maps the range consecutively;
    # `<lo> <hi> [<d1> <d2> ...]` maps each code to its own destination. Reading
    # the second as the first takes the array's first element as a base and
    # walks it upward, which yields a plausible-looking alphabet that is wrong
    # for every character after the first.
    pattern = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*"
                         rb"(?:\[([^\]]*)\]|<([0-9A-Fa-f\s]+)>)")
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", stream, re.S):
        for lo, hi, arr, dst in pattern.findall(block):
            start_code, end_code = int(lo, 16), int(hi, 16)
            if arr:
                for i, item in enumerate(re.findall(rb"<([0-9A-Fa-f\s]+)>", arr)):
                    if start_code + i <= end_code:
                        table[start_code + i] = to_str(item)
            elif dst:
                base = int(re.sub(rb"\s+", b"", dst), 16)
                for i in range(min(end_code - start_code + 1, 65536)):
                    table[start_code + i] = chr(base + i)
    return table


def _resolve(blob: bytes, key: bytes, objects: dict[int, bytes]) -> bytes:
    """Value of /key from a dictionary, following one indirect reference.

    A page rarely holds its fonts inline. It points at /Resources, which points
    at /Font, which points at the font objects, and any of those hops can be an
    indirect reference."""
    ref = re.search(key + rb"\s+(\d+)\s+\d+\s+R", blob)
    if ref:
        return objects.get(int(ref.group(1)), b"")
    inline = re.search(key + rb"\s*<<", blob)
    if not inline:
        return b""
    start = inline.end() - 2
    depth, i = 0, start
    while i < len(blob) - 1:
        pair = blob[i:i + 2]
        if pair == b"<<":
            depth += 1
            i += 2
        elif pair == b">>":
            depth -= 1
            i += 2
            if depth == 0:
                return blob[start:i]
        else:
            i += 1
    return blob[start:]


def _fonts(page_body: bytes, objects: dict[int, bytes],
           gens: dict[int, int] | None = None, dec=None) -> dict[str, dict]:
    """{font resource name: {code: char}} for the fonts this page uses."""
    gens = gens or {}
    out: dict[str, dict] = {}
    resources = _resolve(page_body, b"/Resources", objects) or page_body
    block = _resolve(resources, b"/Font", objects) or resources
    for match in re.finditer(rb"(/[^\s/\[\]<>(){}]+)\s+(\d+)\s+\d+\s+R", block):
        name, num = match.group(1), match.group(2)
        font = objects.get(int(num))
        if font is None:
            continue
        tu = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", font)
        if not tu:
            continue
        tu_num = int(tu.group(1))
        stream = _stream_bytes(objects.get(tu_num, b""), objects,
                               tu_num, gens.get(tu_num, 0), dec)
        if not stream:
            continue
        # A Type0 / Identity-H font addresses glyphs with two bytes. Reading it
        # one byte at a time yields a stream of stray characters that looks like
        # text and is not, which is worse than failing.
        wide = bool(re.search(rb"/Subtype\s*/Type0", font)
                    or re.search(rb"/Encoding\s*/Identity-[HV]", font))
        out[name.decode("latin-1")] = {"map": _tounicode(stream),
                                       "bytes": 2 if wide else 1}
    return out


def _dictionary_of(obj: bytes) -> bytes:
    """The dictionary part of an indirect object, without its stream payload.

    An uncompressed image whose raster bytes happen to contain `/Subtype /Form`
    would otherwise be spliced into the content stream as text."""
    marker = re.search(rb"\bstream\r?\n", obj)
    return obj[:marker.start()] if marker else obj


def _page_resources(body: bytes, objects: dict[int, bytes]) -> bytes:
    """A page's /Resources, following /Parent where the page inherits them.

    /Resources is an inheritable attribute: a page may carry none and take the
    /Pages node's instead. Looking only at the page body finds no /XObject in
    that entirely valid layout, and the page's own footer then passes the
    density gate while the form holding the document is never read."""
    seen: set[int] = set()
    node = body
    for _ in range(MAX_PAGE_TREE_DEPTH):
        resources = _resolve(node, b"/Resources", objects)
        if resources:
            return resources
        parent = re.search(rb"/Parent\s+(\d+)\s+\d+\s+R", node)
        if not parent:
            break
        number = int(parent.group(1))
        if number in seen:
            break
        seen.add(number)
        node = objects.get(number, b"")
        if not node:
            break
    return b""


def _blank_strings(content: bytes) -> bytes:
    """Blank out literal-string bodies, keeping every offset. A font name drawn
    as text is not a font operand."""
    out = bytearray(content)
    i, n = 0, len(content)
    while i < n:
        if content[i:i + 1] != b"(":
            i += 1
            continue
        depth, i = 1, i + 1
        while i < n and depth:
            c = content[i:i + 1]
            if c == b"\\":
                out[i:i + 2] = b"  "
                i += 2
                continue
            depth += (c == b"(") - (c == b")")
            if depth:
                out[i:i + 1] = b" "
            i += 1
    return bytes(out)


def _strip_comments(content: bytes) -> bytes:
    """Blank out `%` comments, which run to end of line.

    TOKEN reads the words inside a comment as operators, so `/Xf % draw body`
    followed by `Do` loses the invocation, and `% /Xf Do` fabricates one. A
    `%` inside a literal string is data, so strings are walked over intact.
    Replaced with spaces rather than removed, to keep every offset stable."""
    out = bytearray(content)
    i, n = 0, len(content)
    while i < n:
        ch = content[i:i + 1]
        if ch == b"(":                       # literal string: find its close
            depth, i = 1, i + 1
            while i < n and depth:
                c = content[i:i + 1]
                if c == b"\\":
                    i += 2
                    continue
                depth += (c == b"(") - (c == b")")
                i += 1
            continue
        if ch == b"%":
            while i < n and content[i:i + 1] not in (b"\n", b"\r"):
                out[i:i + 1] = b" "
                i += 1
            continue
        i += 1
    return bytes(out)


def _pdf_name(raw: str) -> str:
    """A PDF name with its #XX escapes resolved.

    `/Body#5FForm` in a resource dictionary and `/Body_Form` at the invocation
    are the same name; comparing the raw spellings left the Form unexpanded and
    reported nothing."""
    out, i = [], 0
    while i < len(raw):
        if raw[i] == "#" and i + 2 < len(raw):
            try:
                out.append(chr(int(raw[i + 1:i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(raw[i])
        i += 1
    return "".join(out)


def _invoked_names(content: bytes) -> list[str]:
    """XObject names this content actually draws, in `/Name Do` order.

    A resource dictionary may hold templates the page never invokes — an
    alternate layout, a superseded revision. Walking the dictionary rather than
    the content stream reports their text, including amounts, as page content."""
    names: list[str] = []
    pending: str | None = None
    for match in TOKEN.finditer(_strip_comments(content)):
        kind, value = match.lastgroup, match.group()
        if kind == "name":
            pending = _pdf_name(value[1:].decode("latin-1"))
        elif kind == "op":
            if value == b"Do" and pending is not None:
                names.append(pending)
            pending = None
    return names


def _scope_font_names(content: bytes, resources: bytes,
                      objects: dict[int, bytes], suffix: str) -> tuple[bytes, dict[str, str]]:
    """Rename this scope's font resources so a flat table cannot collide.

    Two Forms may both call a font `/F1` and mean different fonts with different
    ToUnicode maps. Merging them into one page-wide dictionary lets whichever
    was merged last decode the other's text — plausible characters, wrong ones,
    with nothing to notice it. Renaming per scope keeps a flat table correct."""
    block = _resolve(resources, b"/Font", objects)
    if not block:
        return content, {}
    mapping: dict[str, str] = {}
    for match in re.finditer(rb"(/[^\s/\[\]<>(){}]+)\s+\d+\s+\d+\s+R", block):
        original = match.group(1).decode("latin-1")
        mapping[original] = f"{original}__x{suffix}"
    # Only the operand of Tf. Resource categories are independent namespaces, so
    # a Form with both a font /F1 and an XObject /F1 had its `/F1 Do` rewritten
    # to an unmapped name and the nested section vanished without a word.
    # Scan a copy with strings and comments blanked, then rewrite the original
    # at those offsets. `(/F1 12 Tf)` is text a document draws, not an operand.
    scannable = _blank_strings(_strip_comments(content))
    out, cursor = bytearray(), 0
    for match in re.finditer(rb"/([^\s/\[\]<>(){}]+)(\s+[-+0-9.]+\s+Tf)",
                             scannable):
        scoped = mapping.get("/" + match.group(1).decode("latin-1"))
        if not scoped:
            continue
        out += content[cursor:match.start()]
        out += b"/" + scoped[1:].encode("latin-1") + match.group(2)
        cursor = match.end()
    out += content[cursor:]
    return bytes(out), mapping


def _expand_forms(content: bytes, resources: bytes, objects: dict[int, bytes],
                  gens: dict[int, int], dec, fonts: dict[str, dict],
                  active: set[int], scope: list[int],
                  depth: int = 0) -> tuple[bytes, bool]:
    """Inline every Form XObject this content invokes, in place of its `Do`.

    Returns the expanded content and whether anything was lost expanding it.

    Inlining at the invocation site rather than appending is what makes the
    graphics state right: the form is emitted between the `q`/`Q` that already
    surround its `Do`, with its own `/Matrix` concatenated, so `_page_text`
    positions it where it was drawn. Appending put every form at the page
    origin, which interleaves two forms drawn at different translations.

    [observed 2026-07-31, one real employer-issued Form 16] A page can draw
    almost nothing itself and invoke a Form XObject with ``Do`` that carries the
    whole document. That certificate's page content stream was 144 bytes — a
    page-number footer and ``/Xf1 Do`` — so reading only ``/Contents`` returned
    the four characters ``1of9`` across nine pages, and the file was then
    refused as undecodable. The refusal named font encoding, which was not the
    cause. `[inferred]` Composing a page this way is ordinary practice for the
    PDF writers used in this domain; only that one document was observed.

    A Form XObject carries its own ``/Resources``, and two of them may both call
    a font ``/F1`` meaning different fonts. Each scope's font names are rewritten
    with a unique suffix, so a flat font table stays correct.

    `active` holds the forms currently being expanded further up the stack, so
    two Form XObjects that invoke each other terminate. It is deliberately not a
    page-wide "seen" set: two parents may legitimately share one child, and one
    form may appear under two resource names, and treating the second use as a
    cycle dropped real text with nothing reported. Exceeding the depth cap is
    reported as loss rather than returning a truncated document that the density
    gate would then accept."""
    if depth > MAX_FORM_XOBJECT_DEPTH or scope[1] > MAX_FORM_EXPANSION_BYTES:
        return content, True
    names = _invoked_names(content)
    if not names:
        return content, False
    block = _resolve(resources, b"/XObject", objects)
    if not block:
        return content, False
    # The same name grammar TOKEN uses. A narrower allowlist omitted valid
    # names such as /Body_Form, leaving the invocation unexpanded and unreported.
    by_name = {_pdf_name(match.group(1).decode("latin-1")): int(match.group(2))
               for match in re.finditer(
                   rb"/([^\s/\[\]<>(){}]+)\s+(\d+)\s+\d+\s+R", block)}
    lost = False
    replacements: dict[str, bytes] = {}
    for name in dict.fromkeys(names):
        scope[1] += sum(1 for n in names if n == name) * 64
        number = by_name.get(name)
        if number is None:
            # The page draws something this resource dictionary does not
            # resolve. Whatever it held is missing from the text.
            lost = True
            continue
        if number in active:
            # A true cycle: this form is already being expanded further up the
            # stack. Dropping the recursive invocation is the only way to
            # terminate, and what remains is a finite prefix of a drawing that
            # cannot be reproduced — so it is loss, not a clean expansion.
            replacements[name] = b""
            lost = True
            continue
        xobject = objects.get(number)
        # Only /Form carries content operators, and the check reads the
        # dictionary alone so an image's raster bytes cannot spoof it.
        if xobject is None or not re.search(
                rb"/Subtype\s*/Form\b", _dictionary_of(xobject)):
            continue
        piece = _stream_bytes(xobject, objects, number, gens.get(number, 0), dec)
        if piece is None:
            # An unsupported or corrupt filter. Silently dropping the form
            # leaves a page that may still pass the gates while missing its
            # body, so this has to reach the page-level refusal.
            lost = True
            continue
        scope[0] += 1
        suffix = str(scope[0])
        form_resources = _resolve(xobject, b"/Resources", objects) or resources
        piece, renamed = _scope_font_names(
            piece, form_resources, objects, suffix)
        # From form_resources, the same dictionary the renaming used. A Form
        # with no /Resources of its own falls back to the caller's, and looking
        # the font up on the resource-less XObject installed nothing — its
        # glyphs then decoded as Latin-1 with no refusal.
        resolved_fonts = _fonts(form_resources, objects, gens, dec)
        for original, scoped in renamed.items():
            if original in resolved_fonts:
                fonts[scoped] = resolved_fonts[original]
        active.add(number)
        piece, deeper_lost = _expand_forms(
            piece, form_resources, objects, gens, dec, fonts, active, scope,
            depth + 1)
        active.discard(number)
        lost = lost or deeper_lost
        head = _dictionary_of(xobject)
        prefix = bytearray(b"q\n")
        matrix = re.search(rb"/Matrix\s*\[\s*([-+0-9.eE\s]+?)\]", head)
        if matrix:
            numbers = matrix.group(1).split()
            if len(numbers) == 6:
                prefix += b" ".join(numbers) + b" cm\n"
        # A Form's contents are clipped to its /BBox. Emitting it as an ordinary
        # `re W n` means the replay honours it the same way it honours any other
        # clip, so a template carrying a stale amount outside its visible crop
        # cannot inject that amount into the statement.
        bbox = re.search(rb"/BBox\s*\[\s*([-+0-9.eE\s]+?)\]", head)
        if bbox:
            numbers = [float(v) for v in bbox.group(1).split()]
            if len(numbers) == 4:
                x0, y0, x1, y1 = numbers
                prefix += (b"%g %g %g %g re W n\n"
                           % (min(x0, x1), min(y0, y1),
                              abs(x1 - x0), abs(y1 - y0)))
        replacement = bytes(prefix) + piece + b"\nQ\n"
        scope[1] += len(replacement)
        if scope[1] > MAX_FORM_EXPANSION_BYTES:
            lost = True
            replacements[name] = b""
            continue
        replacements[name] = replacement

    if not replacements:
        return content, lost

    # Splice each expansion in where its `Do` sits, so the surrounding graphics
    # state applies to it.
    out = bytearray()
    cursor = 0
    pending_name: str | None = None
    pending_start = 0
    for match in TOKEN.finditer(_strip_comments(content)):
        kind, value = match.lastgroup, match.group()
        if kind == "name":
            pending_name = _pdf_name(value[1:].decode("latin-1"))
            pending_start = match.start()
        elif kind == "op":
            if (value == b"Do" and pending_name is not None
                    and pending_name in replacements):
                out += content[cursor:pending_start]
                out += replacements[pending_name]
                cursor = match.end()
            pending_name = None
    out += content[cursor:]
    return bytes(out), lost


def _glyph_size(tf_size: float, tm_scale: float, ctm: list[float]) -> float:
    """Device-space size of a glyph: the Tf size through both matrices."""
    return (tf_size or 10.0) * (tm_scale or 1.0) * (abs(ctm[0]) or 1.0)


def _matrix_mul(m: list[float], n: list[float]) -> list[float]:
    """PDF 3x3 matrix product for the six-element [a b c d e f] form."""
    return [m[0] * n[0] + m[1] * n[2],
            m[0] * n[1] + m[1] * n[3],
            m[2] * n[0] + m[3] * n[2],
            m[2] * n[1] + m[3] * n[3],
            m[4] * n[0] + m[5] * n[2] + n[4],
            m[4] * n[1] + m[5] * n[3] + n[5]]


def _decode(raw: bytes, font: dict | None) -> str:
    if not font:
        return raw.decode("latin-1", "replace")
    table = font["map"]
    if font["bytes"] == 2:
        return "".join(table.get(int.from_bytes(raw[i:i + 2], "big"), "")
                       for i in range(0, len(raw) - 1, 2))
    return "".join(table.get(b, "") for b in raw)


def _page_text(content: bytes, fonts: dict[str, dict]) -> str:
    """Replay the text operators onto a character grid.

    Position matters: a tax statement is a table, and text that arrives in
    drawing order reads as noise unless it is put back where it was drawn."""
    lines: dict[int, dict[int, str]] = {}
    stack: list = []
    tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    line_m = tm[:]
    # The current transformation matrix, and the q/Q stack it is saved on. Text
    # is positioned by the text matrix *concatenated with* the CTM, so ignoring
    # `cm` puts every glyph at its local coordinates. Two Form XObjects drawn at
    # different translations then land on the same grid row and interleave
    # character by character, which reads as text and is not.
    ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    clip = None            # list of visible boxes in device space, or None
    pending_rect: list = []
    path_is_rectangles = True
    path_points: list = []
    gs_stack: list = []
    # The size a glyph is drawn at is the Tf size scaled by the text matrix and
    # then by the CTM. Reading it off the text matrix alone — as this did —
    # loses the Tf size entirely, and a document that carries its scale in the
    # CTM and leaves Tm at unity collapses the column unit to a fraction of a
    # point. Every glyph then lands many columns from its neighbour and a word
    # arrives as single letters separated by spaces.
    tf_size, leading, cmap = 10.0, 12.0, None
    tm_scale = 1.0
    char_w = 0.5          # average glyph width as a fraction of font size

    def put(text: str):
        if not text.strip():
            return
        x = ctm[0] * tm[4] + ctm[2] * tm[5] + ctm[4]
        y = ctm[1] * tm[4] + ctm[3] * tm[5] + ctm[5]
        # A viewer paints nothing outside the clip, so neither does this. A
        # Form's /BBox arrives here as a clip; an invoked template holding a
        # superseded amount outside its visible crop must not reach the caller.
        if clip is not None and not any(
                box[0] - 1 <= x <= box[2] + 1 and box[1] - 1 <= y <= box[3] + 1
                for box in clip):
            tm[4] += (len(text) * (tf_size or 10.0) * (tm_scale or 1.0)
                      * char_w)
            return
        size = _glyph_size(tf_size, tm_scale, ctm)
        row = int(round(-y / 9.6))
        col = int(round(x / (size * char_w))) if size else 0
        cells = lines.setdefault(row, {})
        # Grid placement uses the composed size; the text-matrix advance must
        # not, because tm[4] is transformed by the CTM again for the next
        # string. Advancing by the composed size counts the CTM twice, which
        # merges labels under a scale below 1 and splits them above it.
        step = size * char_w
        text_step = (tf_size or 10.0) * (tm_scale or 1.0) * char_w
        for index, ch in enumerate(text):
            if clip is not None:
                # `step` is already device-space: `size` carries the CTM. Scaling
                # it again here counts the CTM twice, so the probe walks the row
                # slower than the glyphs do and clipped text reaches the caller.
                gx = x + (step * index)
                if not any(box[0] - 1 <= gx <= box[2] + 1
                           and box[1] - 1 <= y <= box[3] + 1 for box in clip):
                    continue
            while col + index in cells and cells[col + index] != " ":
                col += 1
            cells[col + index] = ch
        tm[4] += len(text) * text_step

    for m in TOKEN.finditer(content):
        kind, value = m.lastgroup, m.group()
        if kind == "str":
            stack.append(("s", _unescape(value[1:-1])))
        elif kind == "hex":
            hexed = re.sub(rb"[^0-9A-Fa-f]", b"", value[1:-1])
            if len(hexed) % 2:
                hexed += b"0"
            stack.append(("s", bytes.fromhex(hexed.decode("ascii"))))
        elif kind == "num":
            stack.append(("n", float(value)))
        elif kind == "name":
            stack.append(("f", value.decode("latin-1")))
        elif kind == "arr":
            stack.append(("[", value))
        elif kind == "op":
            op = value.decode("latin-1")
            nums = [v for k, v in stack if k == "n"]
            if op == "q":
                # The graphics state includes the text state: font, size and
                # leading are saved and restored with it. Keeping only the CTM
                # let a Form's font stay selected after its Q, so text the page
                # drew afterwards decoded against the Form's map.
                gs_stack.append((ctm[:], cmap, tf_size, leading, clip))
            elif op == "Q":
                if gs_stack:
                    ctm, cmap, tf_size, leading, clip = gs_stack.pop()
            elif op == "cm" and len(nums) >= 6:
                ctm = _matrix_mul(nums[-6:], ctm)
            elif op == "re" and len(nums) >= 4:
                pending_rect.append(nums[-4:])
            elif op in ("n", "f", "F", "S", "s", "B", "b"):
                path_is_rectangles = True
                path_points = []
            elif op in ("m", "l", "c", "v", "y"):
                # Curve and line segments. Their control points bound the path,
                # which is all this replay needs: see the note on W.
                for i in range(0, len(nums) - 1, 2):
                    path_points.append((nums[i], nums[i + 1]))
                path_is_rectangles = False
            elif op == "h":
                pass
            elif op in ("n", "f", "F", "S", "s", "B", "b") and pending_rect:
                # Painted or discarded without W: the path is spent, and a
                # later W must not pick these rectangles up.
                pending_rect = []
            elif op == "W*" or (op == "W" and not path_is_rectangles):
                # A path of lines and curves, or an even-odd rule. The visible
                # region is not a union of rectangles. Refusing the page would
                # reject documents that clip decoratively all the time, and
                # ignoring the clip entirely would surface text a viewer never
                # paints — so the path's bounding box is used. That is
                # deliberately over-inclusive: text far outside the path is
                # dropped, text inside a concavity may survive. It never hides
                # anything a viewer shows.
                points = list(path_points)
                for rx, ry, rw, rh in pending_rect:
                    points += [(rx, ry), (rx + rw, ry),
                               (rx, ry + rh), (rx + rw, ry + rh)]
                if points:
                    xs = [ctm[0] * cx + ctm[2] * cy + ctm[4]
                          for cx, cy in points]
                    ys = [ctm[1] * cx + ctm[3] * cy + ctm[5]
                          for cx, cy in points]
                    box = (min(xs), min(ys), max(xs), max(ys))
                    clip = [box] if clip is None else [
                        b for b in ((max(a[0], box[0]), max(a[1], box[1]),
                                     min(a[2], box[2]), min(a[3], box[3]))
                                    for a in clip)
                        if b[0] <= b[2] and b[1] <= b[3]]
                pending_rect = []
                path_points = []
                path_is_rectangles = True
            elif op == "W":
                # `re re W n` clips to both rectangles, so the new region is
                # their union. Taking only the last one dropped text a viewer
                # paints through the first.
                if pending_rect:
                    boxes = []
                    for rx, ry, rw, rh in pending_rect:
                        xs, ys = [], []
                        for cx, cy in ((rx, ry), (rx + rw, ry),
                                       (rx, ry + rh), (rx + rw, ry + rh)):
                            xs.append(ctm[0] * cx + ctm[2] * cy + ctm[4])
                            ys.append(ctm[1] * cx + ctm[3] * cy + ctm[5])
                        boxes.append((min(xs), min(ys), max(xs), max(ys)))
                    # Each subpath is its own visible region. Collapsing two
                    # disjoint rectangles into one bounding box makes the gap
                    # between them visible, which is the opposite of clipping.
                    if clip is None:
                        clip = boxes
                    else:
                        merged = []
                        for a in clip:
                            for b in boxes:
                                box = (max(a[0], b[0]), max(a[1], b[1]),
                                       min(a[2], b[2]), min(a[3], b[3]))
                                if box[0] <= box[2] and box[1] <= box[3]:
                                    merged.append(box)
                        clip = merged
                pending_rect = []
            elif op == "Tf":
                names = [v for k, v in stack if k == "f"]
                if names:
                    cmap = fonts.get(names[-1])
                if nums:
                    tf_size = abs(nums[-1]) or 10.0
            elif op == "TL" and nums:
                leading = nums[-1]
            elif op == "Tm" and len(nums) >= 6:
                tm = nums[-6:]
                # The matrix scales the Tf size; it does not replace it.
                tm_scale = abs(tm[0]) or 1.0
                line_m = tm[:]
            elif op in ("Td", "TD") and len(nums) >= 2:
                line_m = [line_m[0], line_m[1], line_m[2], line_m[3],
                          line_m[4] + nums[-2], line_m[5] + nums[-1]]
                tm = line_m[:]
                if op == "TD":
                    leading = -nums[-1]
            elif op == "T*":
                line_m[5] -= leading
                tm = line_m[:]
            elif op == "BT":
                tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
                line_m = tm[:]
                tm_scale = 1.0
            elif op in ("Tj", "'", '"'):
                if op != "Tj":
                    line_m[5] -= leading
                    tm = line_m[:]
                for k, v in stack:
                    if k == "s":
                        put(_decode(v, cmap))
            elif op == "TJ":
                for k, v in stack:
                    if k == "s":
                        put(_decode(v, cmap))
                    elif k == "n" and v < -120:
                        # A TJ kern is in thousandths of the Tf size, before
                        # either matrix — the text matrix advances in its own
                        # space, so only the Tf size applies here.
                        tm[4] += -v / 1000.0 * tf_size
            stack = []

    out = []
    for row in sorted(lines):
        cells = lines[row]
        width = max(cells) + 1
        out.append("".join(cells.get(i, " ") for i in range(width)).rstrip())
    return "\n".join(out)


def extract_pages(path: str, password: str | None = None) -> list[str]:
    name = safe_name(path)
    with open(path, "rb") as fh:
        data = fh.read()
    if data.startswith(JAVA_STREAM_MAGIC):
        data = _unwrap_java_pdf_envelope(data, name)
        if not data.startswith(b"%PDF"):
            raise PdfError(
                f"{name} is a Java-serialized Object[] whose byte-array "
                "payload is not a PDF.")
    if not data.startswith(b"%PDF"):
        raise PdfError(f"{name} does not start with %PDF")

    dec = None
    if is_encrypted(data):
        try:
            dec = make_decryptor(data, password or "")
        except CryptError as e:
            if password:
                raise PdfError(f"{name}: {e}")
            raise PdfError(
                f"{name} is encrypted and needs a password. AIS, TIS, Form 16 "
                "and the s.143(1) intimation open with the PAN in lowercase "
                "followed by the date of birth as ddmmyyyy — pass it with "
                "--password, or derive it with open_ais.py --print-password. "
                f"({e.args[0].split('.')[0] if e.args else e})")

    try:
        objects, gens = _objects(data)
        _expand_object_streams(objects, gens, dec)
        pages: list[str] = []
        pages_with_decode_loss = 0
        loss_kinds: set[str] = set()
        for num in sorted(objects):
            body = objects[num]
            if not re.search(rb"/Type\s*/Page\b", body):
                continue
            refs = re.findall(
                rb"/Contents\s+(?:(\d+)\s+\d+\s+R|\[([^\]]*)\])", body)
            stream_ids: list[int] = []
            for single, array in refs:
                if single:
                    stream_ids.append(int(single))
                else:
                    stream_ids += [int(x) for x in re.findall(
                        rb"(\d+)\s+\d+\s+R", array)]
            content = b""
            stream_failed = False
            for sid in stream_ids:
                piece = _stream_bytes(objects.get(sid, b""), objects,
                                      sid, gens.get(sid, 0), dec)
                if piece is None:
                    stream_failed = True
                elif piece:
                    content += piece + b"\n"
            # The page may draw its body through a Form XObject rather than in
            # its own content stream. Those streams are part of the page, not an
            # extra, and are inlined where their `Do` sits.
            resources = _page_resources(body, objects)
            fonts = _fonts(resources, objects, gens, dec)
            content, form_loss = _expand_forms(
                content, resources, objects, gens, dec, fonts, set(), [0, 0])
            text = _page_text(content, fonts) if content else ""
            pages.append(text)
            kind = _page_loss_kind(content, text, stream_failed)
            if form_loss and not kind:
                kind = "forms"
            if kind:
                pages_with_decode_loss += 1
                loss_kinds.add("forms" if form_loss and kind == "stream"
                               else kind)
    except CryptError as e:
        raise PdfError(f"{name}: {e}") from None

    if not pages:
        raise PdfError(
            f"{name} has no readable pages. If it opens in a viewer, the page "
            "objects are in a structure this reader does not decode — run "
            "read_pdf.py on it and open an issue with the PDF version from the "
            "first line of the file.")
    # [observed 2026-07-30] All 24 pages across the 15 committed fixtures have
    # decodable text streams and at least one word; none exercises this refusal.
    # [inferred] Missing content, or an empty stream that decoded successfully,
    # can be a genuine blank; decoded content with no text-showing operator can
    # be an image-only page. Neither is evidence of loss. An undecodable stream
    # or text operators yielding no words is. This page-level gate catches whole-
    # page loss; the document-density gate below separately catches glyph noise.
    if pages_with_decode_loss:
        detail = {
            "stream": "a content stream that would not decode",
            "wordless": "text-showing operators but no readable words",
            "glyphs": ("letters that mostly do not form words, which is what "
                       "unmapped glyphs look like"),
            "forms": ("a Form XObject this reader could not expand faithfully — "
                      "a cyclic drawing, a stream that would not decode, an "
                      "unresolved invocation, or an expansion past its budget"),
        }
        seen_detail = "; ".join(detail[k] for k in
                                ("stream", "wordless", "glyphs", "forms")
                                if k in loss_kinds)
        raise PdfError(
            f"{name}: could not read {pages_with_decode_loss} of "
            f"{len(pages)} pages. What was wrong with them: {seen_detail}. "
            "Treat the document as incomplete, never as an empty statement.")
    if not any(p.strip() for p in pages):
        raise PdfError(
            f"{name} has no text layer — it is probably a scan. This reader does "
            "no OCR. Treat it as unreadable, never as an empty statement.")
    if not _has_plausible_word_density(pages):
        raise PdfError(
            f"{name}: text was extracted, but it does not form words. This "
            "test measures that result and observes no cause. `[inferred]` The "
            "usual explanations are a font encoding this reader cannot map, or "
            "text drawn somewhere it does not look; neither is established "
            "here. Treat it as unreadable, never as an empty statement.")
    return pages


def extract_text(path: str, password: str | None = None) -> str:
    return "\n".join(extract_pages(path, password))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, help="1-based page number")
    ap.add_argument("--password", help="for AIS, TIS, Form 16 and the s.143(1) "
                                       "intimation: lowercase PAN + ddmmyyyy")
    ap.add_argument("--password-stdin", action="store_true",
                    help="read the password from standard input instead, so it "
                         "never appears in argv or in shell history")
    a = ap.parse_args()
    try:
        password = resolve_password(a.password, a.password_stdin)
        pages = extract_pages(a.pdf, password)
    except (PdfError, CryptError) as e:
        print(e, file=sys.stderr)
        raise SystemExit(2)
    if a.page:
        print(pages[a.page - 1] if 0 < a.page <= len(pages) else "")
    else:
        for i, page in enumerate(pages, 1):
            print(f"----- page {i} -----")
            print(page)
