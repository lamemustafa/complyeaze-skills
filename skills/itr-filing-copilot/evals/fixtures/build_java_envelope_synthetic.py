#!/usr/bin/env python3
"""Rebuild the synthetic Java-serialized PDF envelope. Standard library only.

    python3 build_java_envelope_synthetic.py

[observed 2026-07-30] The e-filing portal can return a Java-serialized
``Object[]`` whose first element is an HTTP-header ``HashMap`` and whose second
element is a ``byte[]`` containing the PDF. The class names and wire shape here
follow that observed envelope; every header value is invented, and the payload
is the existing synthetic PDF fixture.

The declared ``byte[]`` length is written explicitly and is the source of
truth. The generated file keeps its portal-style ``.pdf`` extension on purpose:
the reader must inspect its bytes rather than trust its name.
"""
from __future__ import annotations

import struct
import sys


STREAM_HEADER = b"\xac\xed\x00\x05"
TC_NULL = b"\x70"
TC_OBJECT = b"\x73"
TC_STRING = b"\x74"
TC_ARRAY = b"\x75"
TC_CLASSDESC = b"\x72"
TC_BLOCKDATA = b"\x77"
TC_ENDBLOCKDATA = b"\x78"


def _utf(text: str) -> bytes:
    encoded = text.encode("ascii")
    if len(encoded) > 0xFFFF:
        raise ValueError("synthetic Java string is too long")
    return struct.pack(">H", len(encoded)) + encoded


def _class_desc(name: str, serial_uid: int, flags: int,
                fields: tuple[tuple[str, str], ...] = ()) -> bytes:
    out = bytearray(TC_CLASSDESC)
    out += _utf(name)
    out += struct.pack(">Q", serial_uid)
    out += bytes([flags])
    out += struct.pack(">H", len(fields))
    for type_code, field_name in fields:
        out += type_code.encode("ascii") + _utf(field_name)
    out += TC_ENDBLOCKDATA + TC_NULL
    return bytes(out)


def _string(value: str) -> bytes:
    return TC_STRING + _utf(value)


def wrap_java_envelope(payload: bytes) -> bytes:
    """Return a valid serialized ``Object[]{HashMap, byte[]}`` envelope."""
    headers = (
        ("Transfer-Encoding", "chunked"),
        ("Date", "Mon, 01 Jan 2001 00:00:00 GMT"),
        ("Content-Type", "application/pdf"),
    )
    object_array = (
        TC_ARRAY
        + _class_desc("[Ljava.lang.Object;", 0x90CE589F1073296C, 0x02)
        + struct.pack(">I", 2)
    )
    header_map = bytearray(
        TC_OBJECT
        + _class_desc(
            "java.util.HashMap", 0x0507DAC1C31660D1, 0x03,
            (("F", "loadFactor"), ("I", "threshold")),
        )
        + struct.pack(">fI", 0.75, 12)
        + TC_BLOCKDATA
        + b"\x08"
        + struct.pack(">II", 16, len(headers))
    )
    for key, value in headers:
        header_map += _string(key) + _string(value)
    header_map += TC_ENDBLOCKDATA

    byte_array = (
        TC_ARRAY
        + _class_desc("[B", 0xACF317F8060854E0, 0x02)
        + struct.pack(">I", len(payload))
        + payload
    )
    return STREAM_HEADER + object_array + bytes(header_map) + byte_array


def main() -> int:
    source = "plain_synthetic.pdf"
    destination = "java_envelope_synthetic.pdf"
    try:
        with open(source, "rb") as fh:
            payload = fh.read()
    except OSError as exc:
        print(f"refused: {source} could not be read ({exc.strerror})",
              file=sys.stderr)
        return 2
    if not payload.startswith(b"%PDF"):
        print(f"refused: {source} is not a PDF", file=sys.stderr)
        return 2
    envelope = wrap_java_envelope(payload)
    with open(destination, "wb") as fh:
        fh.write(envelope)
    print(f"wrote {destination}: {len(payload)} declared payload bytes, "
          f"{len(envelope)} total bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
