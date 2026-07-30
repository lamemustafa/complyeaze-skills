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
# [observed 2026-07-31] The 15 committed PDFs in evals/fixtures have a minimum
# density of 80.4 three-character word tokens per 1,000 ink characters. Measured
# the old way, against the whole laid-out string, the same minimum was 39.6.
# [observed 2026-07-29] The reported 81-page ITR-3 reproduction measured 0.0.
# [observed 2026-07-31] A real 82-page bank statement that reads perfectly
# measured 1.42 the old way and 57.09 this way; it was being refused.
# [inferred] Five leaves 16x headroom below the weakest fixture. Numeric-heavy
# tables still carry headings; measuring the whole document lets a blank, cover,
# or unusually sparse page coexist with readable pages instead of being refused.
MIN_WORD_TOKENS_PER_1000_CHARS = 5


class PdfError(Exception):
    """The file is not a PDF this reader can decode."""


def _word_tokens(text: str) -> list[str]:
    """Return words made of Unicode letters and their combining marks."""
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
        if len(current) >= 3:
            words.append("".join(current))
        current = []
    if len(current) >= 3:
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
    was 1.42 and it failed a threshold of 5; against ink it is 57.09. Wide
    numeric documents — bank statements, Form 26AS, broker reports — are exactly
    the shape that trends toward a false refusal as the page gets wider."""
    text = "\n".join(pages)
    ink = sum(1 for char in text if not char.isspace())
    if not ink:
        return False
    words = len(_word_tokens(text))
    return words * 1000 >= MIN_WORD_TOKENS_PER_1000_CHARS * ink


def _has_text_showing_operator(content: bytes) -> bool:
    return any(m.lastgroup == "op" and m.group() in TEXT_SHOWING_OPERATORS
               for m in TOKEN.finditer(content))


def _page_lost_text(content: bytes, text: str, stream_failed: bool) -> bool:
    """Whether a page attempted text extraction but lost all readable words."""
    if stream_failed:
        return True
    return (_has_text_showing_operator(content)
            and not _word_tokens(text))


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
    for name, num in re.findall(rb"(/[A-Za-z0-9#+.\-]+)\s+(\d+)\s+\d+\s+R", block):
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
    font_size, leading, cmap = 10.0, 12.0, None
    char_w = 0.5          # average glyph width as a fraction of font size

    def put(text: str):
        if not text.strip():
            return
        x, y = tm[4], tm[5]
        row = int(round(-y / 9.6))
        col = int(round(x / (font_size * char_w))) if font_size else 0
        cells = lines.setdefault(row, {})
        for ch in text:
            while col in cells and cells[col] != " ":
                col += 1
            cells[col] = ch
            col += 1
        tm[4] += len(text) * font_size * char_w

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
            if op == "Tf":
                names = [v for k, v in stack if k == "f"]
                if names:
                    cmap = fonts.get(names[-1])
                if nums:
                    font_size = abs(nums[-1]) or 10.0
            elif op == "TL" and nums:
                leading = nums[-1]
            elif op == "Tm" and len(nums) >= 6:
                tm = nums[-6:]
                font_size = abs(tm[0]) or font_size
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
                        tm[4] += -v / 1000.0 * font_size
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
            text = (_page_text(content, _fonts(body, objects, gens, dec))
                    if content else "")
            pages.append(text)
            if _page_lost_text(content, text, stream_failed):
                pages_with_decode_loss += 1
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
        raise PdfError(
            f"{name}: could not decode text from {pages_with_decode_loss} of "
            f"{len(pages)} pages. Those pages had referenced content streams "
            "or text-showing operators, but no readable words. Treat the "
            "document as incomplete, never as an empty statement.")
    if not any(p.strip() for p in pages):
        raise PdfError(
            f"{name} has no text layer — it is probably a scan. This reader does "
            "no OCR. Treat it as unreadable, never as an empty statement.")
    if not _has_plausible_word_density(pages):
        raise PdfError(
            f"{name}: text was extracted, but it does not form words. The pages "
            "may use a font encoding this reader cannot map, or may draw their "
            "text somewhere it does not look. This test measures the result, "
            "not the cause. Treat it as unreadable, never as an empty statement.")
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
