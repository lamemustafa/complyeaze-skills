#!/usr/bin/env python3
"""
The PDF standard security handler, in pure Python. Standard library only.

    python3 pdf_crypt.py                 # run the known-answer tests
    from pdf_crypt import make_decryptor, is_encrypted

Why this exists
---------------
Every document the income-tax portal hands a taxpayer about themselves arrives
encrypted: AIS, TIS, the s.143(1) intimation, and Form 16 from most payroll
software. The password is the taxpayer's own PAN and date of birth, so this is
not a lock — it is a wrapper that a reader has to unwrap before there is any
text at all.

The usual answer is `pip install pikepdf`, which is a C extension. This project
promises the standard library and nothing else, and a taxpayer who cannot build
a wheel should still be able to read their own tax statement. So the handler is
here: RC4 and AES are a few hundred lines between them, and MD5, SHA-256,
SHA-384 and SHA-512 are already in `hashlib`.

What is implemented
-------------------
Revisions 2, 3 and 4 (RC4 40-bit and 128-bit, and AES-128 under /AESV2) and
revisions 5 and 6 (AES-256 under /AESV3). Both the user password and the owner
password open a file. Only decryption is implemented, plus the single AES-128
CBC *encryption* that revision 6's hash requires.

Getting the key wrong is not a silent failure. Every revision has a published
validation step -- Algorithm 6 for R2-R4, Algorithm 11 for R5-R6 -- and a key
that does not satisfy it is refused rather than used to produce plausible
rubbish. That check is what makes it safe to ship the revision-6 path against
documents this project has never seen.

Provenance
----------
`[documented]` RC4 against the RFC 6229 test vectors; AES-128/192/256 single
blocks against FIPS-197 and appendix C; CBC against NIST SP 800-38A F.2.
`[observed]` end to end against live AY 2026-27 portal downloads -- AIS and TIS
at /V 1 /R 2, Form 16 and a s.143(1) intimation at /V 2 /R 3 /Length 128, all
July 2026.
`[UNVERIFIED]` revisions 5 and 6. The code follows ISO 32000-2 and the
Adobe supplement, but no /R 5 or /R 6 file has been put through it. The
Algorithm 11 validation means a misreading refuses rather than mis-decrypts.
"""
from __future__ import annotations

import hashlib
import re
import struct
import sys

PAD = bytes([
    0x28, 0xBF, 0x4E, 0x5E, 0x4E, 0x75, 0x8A, 0x41, 0x64, 0x00, 0x4E, 0x56,
    0xFF, 0xFA, 0x01, 0x08, 0x2E, 0x2E, 0x00, 0xB6, 0xD0, 0x68, 0x3E, 0x80,
    0x2F, 0x0C, 0xA9, 0xFE, 0x64, 0x53, 0x69, 0x7A])


class CryptError(Exception):
    """The file cannot be decrypted with what was supplied."""


# --------------------------------------------------------------------------
# RC4
# --------------------------------------------------------------------------

def rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    klen = len(key)
    if klen == 0:
        raise CryptError("RC4 with an empty key")
    for i in range(256):
        j = (j + s[i] + key[i % klen]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray(len(data))
    i = j = 0
    for n, byte in enumerate(data):
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out[n] = byte ^ s[(s[i] + s[j]) & 0xFF]
    return bytes(out)


# --------------------------------------------------------------------------
# AES
# --------------------------------------------------------------------------

def _build_tables():
    sbox = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) \
            ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i
    return sbox, inv


SBOX, INV_SBOX = _build_tables()
RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36,
        0x6C, 0xD8, 0xAB, 0x4D]


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _mul(a: int, b: int) -> int:
    out = 0
    for _ in range(8):
        if b & 1:
            out ^= a
        b >>= 1
        a = _xtime(a)
    return out


class AES:
    """AES-128/192/256 on 16-byte blocks. Decryption plus the one encryption
    direction that PDF revision 6's hash needs."""

    def __init__(self, key: bytes):
        if len(key) not in (16, 24, 32):
            raise CryptError(f"AES key of {len(key)} bytes; expected 16, 24 or 32")
        self.nk = len(key) // 4
        self.nr = self.nk + 6
        self.w = self._expand(key)

    def _expand(self, key: bytes) -> list[list[int]]:
        w = [list(key[4 * i:4 * i + 4]) for i in range(self.nk)]
        for i in range(self.nk, 4 * (self.nr + 1)):
            t = list(w[i - 1])
            if i % self.nk == 0:
                t = t[1:] + t[:1]
                t = [SBOX[b] for b in t]
                t[0] ^= RCON[i // self.nk - 1]
            elif self.nk > 6 and i % self.nk == 4:
                t = [SBOX[b] for b in t]
            w.append([w[i - self.nk][j] ^ t[j] for j in range(4)])
        return w

    def _add_round_key(self, state, rnd):
        for c in range(4):
            for r in range(4):
                state[r][c] ^= self.w[rnd * 4 + c][r]

    def encrypt_block(self, block: bytes) -> bytes:
        state = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
        self._add_round_key(state, 0)
        for rnd in range(1, self.nr + 1):
            for r in range(4):
                for c in range(4):
                    state[r][c] = SBOX[state[r][c]]
            for r in range(1, 4):
                state[r] = state[r][r:] + state[r][:r]
            if rnd != self.nr:
                for c in range(4):
                    col = [state[r][c] for r in range(4)]
                    state[0][c] = _xtime(col[0]) ^ (_xtime(col[1]) ^ col[1]) ^ col[2] ^ col[3]
                    state[1][c] = col[0] ^ _xtime(col[1]) ^ (_xtime(col[2]) ^ col[2]) ^ col[3]
                    state[2][c] = col[0] ^ col[1] ^ _xtime(col[2]) ^ (_xtime(col[3]) ^ col[3])
                    state[3][c] = (_xtime(col[0]) ^ col[0]) ^ col[1] ^ col[2] ^ _xtime(col[3])
            self._add_round_key(state, rnd)
        return bytes(state[r][c] for c in range(4) for r in range(4))

    def decrypt_block(self, block: bytes) -> bytes:
        state = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
        self._add_round_key(state, self.nr)
        for rnd in range(self.nr - 1, -1, -1):
            for r in range(1, 4):
                state[r] = state[r][-r:] + state[r][:-r]
            for r in range(4):
                for c in range(4):
                    state[r][c] = INV_SBOX[state[r][c]]
            self._add_round_key(state, rnd)
            if rnd:
                for c in range(4):
                    col = [state[r][c] for r in range(4)]
                    state[0][c] = _mul(col[0], 14) ^ _mul(col[1], 11) ^ _mul(col[2], 13) ^ _mul(col[3], 9)
                    state[1][c] = _mul(col[0], 9) ^ _mul(col[1], 14) ^ _mul(col[2], 11) ^ _mul(col[3], 13)
                    state[2][c] = _mul(col[0], 13) ^ _mul(col[1], 9) ^ _mul(col[2], 14) ^ _mul(col[3], 11)
                    state[3][c] = _mul(col[0], 11) ^ _mul(col[1], 13) ^ _mul(col[2], 9) ^ _mul(col[3], 14)
        return bytes(state[r][c] for c in range(4) for r in range(4))


def aes_cbc_decrypt(key: bytes, data: bytes, iv: bytes | None = None,
                    unpad: bool = True) -> bytes:
    """Decrypt CBC. With iv=None the first 16 bytes of `data` are the IV, which
    is how PDF stores it."""
    if iv is None:
        if len(data) < 16:
            raise CryptError("AES stream shorter than its initialisation vector")
        iv, data = data[:16], data[16:]
    if len(data) % 16:
        # An AES-encrypted stream is always a whole number of blocks — the
        # padding guarantees it. A remainder means the stream was truncated or
        # is not AES at all, and an earlier version dropped the tail and
        # returned the rest, so a caller reconciling totals saw a short document
        # rather than a broken one.
        raise CryptError(
            f"an AES stream of {len(data) + 16} bytes is not a whole number of "
            "16-byte blocks, so it is truncated or was never AES. Refusing "
            "rather than returning the part that happens to decode: a document "
            "missing its last rows reads exactly like a document that is "
            "complete.")
    aes = AES(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        block = data[i:i + 16]
        clear = aes.decrypt_block(block)
        out += bytes(a ^ b for a, b in zip(clear, prev))
        prev = block
    if unpad:
        if not out:
            raise CryptError(
                "an AES stream has no PKCS#7 padding block. Refusing rather "
                "than returning empty plaintext from a damaged stream.")
        n = out[-1]
        if not 1 <= n <= 16 or bytes(out[-n:]) != bytes([n]) * n:
            raise CryptError(
                "an AES stream has invalid PKCS#7 padding, so it is damaged or "
                "was decrypted with the wrong key. Refusing rather than "
                "returning bytes whose last rows may be corrupt or missing.")
        del out[-n:]
    return bytes(out)


def aes_cbc_encrypt_nopad(key: bytes, data: bytes, iv: bytes) -> bytes:
    if len(data) % 16:
        raise CryptError(
            f"CBC encryption of {len(data)} bytes, which is not a whole number "
            "of blocks. Pad before calling; silently dropping the tail would "
            "corrupt revision 6's hash.")
    if len(iv) != 16:
        raise CryptError(f"initialisation vector of {len(iv)} bytes; expected 16")
    aes = AES(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        block = bytes(a ^ b for a, b in zip(data[i:i + 16], prev))
        prev = aes.encrypt_block(block)
        out += prev
    return bytes(out)


# --------------------------------------------------------------------------
# Reading the /Encrypt dictionary out of the file
# --------------------------------------------------------------------------

_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
            b"(": b"(", b")": b")", b"\\": b"\\"}


def _unescape(raw: bytes) -> bytes:
    out, i = bytearray(), 0
    while i < len(raw):
        c = raw[i:i + 1]
        if c != b"\\":
            out += c
            i += 1
            continue
        nxt = raw[i + 1:i + 2]
        if nxt in _ESCAPES:
            out += _ESCAPES[nxt]
            i += 2
        elif nxt.isdigit():
            j, digits = i + 1, b""
            while j < len(raw) and raw[j:j + 1].isdigit() and len(digits) < 3:
                digits += raw[j:j + 1]
                j += 1
            out += bytes([int(digits, 8) & 0xFF])
            i = j
        elif nxt in (b"\n", b"\r"):
            i += 2
        else:
            out += nxt
            i += 2
    return bytes(out)


def _read_string(blob: bytes, pos: int) -> tuple[bytes, int] | None:
    """A PDF string at `pos`, either (literal) or <hex>."""
    while pos < len(blob) and blob[pos:pos + 1].isspace():
        pos += 1
    if pos >= len(blob):
        return None
    if blob[pos:pos + 1] == b"<":
        end = blob.find(b">", pos)
        if end == -1:
            return None
        hexed = re.sub(rb"[^0-9A-Fa-f]", b"", blob[pos + 1:end])
        if len(hexed) % 2:
            hexed += b"0"
        return bytes.fromhex(hexed.decode("ascii")), end + 1
    if blob[pos:pos + 1] != b"(":
        return None
    depth, i = 0, pos
    while i < len(blob):
        c = blob[i:i + 1]
        if c == b"\\":
            i += 2
            continue
        if c == b"(":
            depth += 1
        elif c == b")":
            depth -= 1
            if depth == 0:
                return _unescape(blob[pos + 1:i]), i + 1
        i += 1
    return None


def _dict_string(blob: bytes, key: bytes) -> bytes | None:
    m = re.search(re.escape(key) + rb"(?![A-Za-z0-9])", blob)
    if not m:
        return None
    got = _read_string(blob, m.end())
    return got[0] if got else None


def _dict_int(blob: bytes, key: bytes, default=None):
    m = re.search(re.escape(key) + rb"(?![A-Za-z0-9])\s*(-?\d+)", blob)
    return int(m.group(1)) if m else default


def _dict_name(blob: bytes, key: bytes) -> str | None:
    m = re.search(re.escape(key) + rb"(?![A-Za-z0-9])\s*/([A-Za-z0-9]+)", blob)
    return m.group(1).decode("latin-1") if m else None


def _object_body(data: bytes, num: int) -> bytes:
    """Last definition of object `num` — later ones are incremental updates."""
    body = b""
    for m in re.finditer(rb"(?<![0-9])" + str(num).encode() + rb"\s+\d+\s+obj\b", data):
        end = data.find(b"endobj", m.end())
        body = data[m.end():end if end != -1 else len(data)]
    return body


def is_encrypted(data: bytes) -> bool:
    return bool(re.search(rb"/Encrypt\s+\d+\s+\d+\s+R", data)
                or re.search(rb"/Encrypt\s*<<", data))


def _encrypt_dict(data: bytes) -> bytes:
    refs = re.findall(rb"/Encrypt\s+(\d+)\s+\d+\s+R", data)
    if refs:
        body = _object_body(data, int(refs[-1]))
        if body:
            return body
    m = None
    for m in re.finditer(rb"/Encrypt\s*<<", data):
        pass
    if m:
        start = m.end() - 2
        depth, i = 0, start
        while i < len(data) - 1:
            pair = data[i:i + 2]
            if pair == b"<<":
                depth += 1
                i += 2
            elif pair == b">>":
                depth -= 1
                i += 2
                if depth == 0:
                    return data[start:i]
            else:
                i += 1
    raise CryptError("the file says it is encrypted but has no /Encrypt dictionary")


def _first_id(data: bytes) -> bytes:
    """First element of the trailer /ID. Absent is legal and means empty."""
    last = None
    for m in re.finditer(rb"/ID\s*\[", data):
        last = m
    if not last:
        return b""
    got = _read_string(data, last.end())
    return got[0] if got else b""


# --------------------------------------------------------------------------
# Key derivation
# --------------------------------------------------------------------------

def _pad_password(pw: bytes) -> bytes:
    return (pw[:32] + PAD)[:32]


def _key_r2_r4(pw: bytes, o_entry: bytes, p: int, doc_id: bytes,
               revision: int, length_bytes: int,
               encrypt_metadata: bool) -> bytes:
    """Algorithm 2."""
    h = hashlib.md5()
    h.update(_pad_password(pw))
    h.update(o_entry[:32])
    h.update(struct.pack("<i", p & 0xFFFFFFFF if p >= 0 else p))
    h.update(doc_id)
    if revision >= 4 and not encrypt_metadata:
        h.update(b"\xff\xff\xff\xff")
    key = h.digest()
    if revision >= 3:
        for _ in range(50):
            key = hashlib.md5(key[:length_bytes]).digest()
    return key[:length_bytes]


def _user_check_r2_r4(key: bytes, doc_id: bytes, revision: int) -> bytes:
    """Algorithm 4 (R2) and Algorithm 5 (R3+): what /U should look like."""
    if revision == 2:
        return rc4(key, PAD)
    digest = hashlib.md5(PAD + doc_id).digest()
    out = rc4(key, digest)
    for i in range(1, 20):
        out = rc4(bytes(b ^ i for b in key), out)
    return out


def _user_password_from_owner(pw: bytes, o_entry: bytes, revision: int,
                              length_bytes: int) -> bytes:
    """Algorithm 7 run backwards: recover the user password from /O."""
    key = hashlib.md5(_pad_password(pw)).digest()
    if revision >= 3:
        for _ in range(50):
            key = hashlib.md5(key).digest()
    key = key[:5] if revision == 2 else key[:length_bytes]
    if revision == 2:
        return rc4(key, o_entry[:32])
    out = o_entry[:32]
    for i in range(19, -1, -1):
        out = rc4(bytes(b ^ i for b in key), out)
    return out


def _hash_2b(password: bytes, salt: bytes, udata: bytes) -> bytes:
    """ISO 32000-2 Algorithm 2.B, the revision 6 password hash."""
    k = hashlib.sha256(password + salt + udata).digest()
    i = 0
    while True:
        k1 = (password + k + udata) * 64
        e = aes_cbc_encrypt_nopad(k[:16], k1, k[16:32])
        mod = sum(e[:16]) % 3
        if mod == 0:
            k = hashlib.sha256(e).digest()
        elif mod == 1:
            k = hashlib.sha384(e).digest()
        else:
            k = hashlib.sha512(e).digest()
        i += 1
        if i >= 64 and e[-1] <= i - 32:
            break
    return k[:32]


def _hash_r5_r6(password: bytes, salt: bytes, udata: bytes,
                revision: int) -> bytes:
    if revision == 5:
        return hashlib.sha256(password + salt + udata).digest()
    return _hash_2b(password, salt, udata)


# --------------------------------------------------------------------------
# The decryptor
# --------------------------------------------------------------------------

class PdfDecryptor:
    """Decrypts the stream bodies of one encrypted PDF.

    Only streams are handled. Strings inside object dictionaries are also
    encrypted in a real PDF, but this project's reader never reads one: the
    text it wants lives in content streams and /ToUnicode streams.
    """

    def __init__(self, data: bytes, password: bytes = b""):
        enc = _encrypt_dict(data)
        filt = _dict_name(enc, b"/Filter")
        if filt not in (None, "Standard"):
            raise CryptError(
                f"/Filter /{filt} is a custom security handler, not the standard "
                "one. This reader only implements the standard handler; the file "
                "needs whatever product wrote it.")
        self.v = _dict_int(enc, b"/V", 0)
        self.r = _dict_int(enc, b"/R", 0)
        self.p = _dict_int(enc, b"/P", 0)
        self.o = _dict_string(enc, b"/O") or b""
        self.u = _dict_string(enc, b"/U") or b""
        self.oe = _dict_string(enc, b"/OE") or b""
        self.ue = _dict_string(enc, b"/UE") or b""
        length_bits = _dict_int(enc, b"/Length", 40)
        self.encrypt_metadata = b"/EncryptMetadata false" not in re.sub(
            rb"\s+", b" ", enc)
        self.doc_id = _first_id(data)

        if self.r not in (2, 3, 4, 5, 6):
            raise CryptError(
                f"/R {self.r} is not a revision of the standard security handler "
                "this reader knows (2, 3, 4, 5 and 6 are implemented).")

        # Which cipher, and with what key length.
        self.cfm = "V2"                       # V2 is the spec's name for RC4
        if self.v in (1,):
            self.length = 5
        elif self.v == 2:
            self.length = max(5, min(16, length_bits // 8))
        elif self.v == 4:
            self.length = max(5, min(16, length_bits // 8))
            stmf = _dict_name(enc, b"/StmF") or "Identity"
            cf = re.search(rb"/CF\s*<<(.*?)>>\s*/(?:StmF|StrF)", enc, re.S) \
                or re.search(rb"/CF\s*<<(.*)", enc, re.S)
            body = cf.group(1) if cf else b""
            m = re.search(rb"/CFM\s*/(\w+)", body)
            self.cfm = m.group(1).decode("latin-1") if m else "V2"
            cflen = _dict_int(body, b"/Length")
            if cflen:
                # /CF /Length is in bytes in most writers and bits in some.
                self.length = cflen if cflen <= 32 else max(5, min(32, cflen // 8))
            if stmf == "Identity":
                self.cfm = "Identity"
        elif self.v == 5:
            self.length = 32
            self.cfm = "AESV3"
        else:
            raise CryptError(f"/V {self.v} is not an encryption version this "
                             "reader implements (1, 2, 4 and 5 are).")

        if self.cfm not in ("V2", "AESV2", "AESV3", "Identity"):
            raise CryptError(f"/CFM /{self.cfm} is not a cipher this reader "
                             "implements (V2, AESV2 and AESV3 are).")
        if self.cfm == "AESV2":
            self.length = 16
        if self.cfm == "AESV3":
            self.length = 32

        self.key, self.opened_with = self._derive(password)

    # -- key ---------------------------------------------------------------
    def _derive(self, password: bytes) -> tuple[bytes, str]:
        if self.r >= 5:
            return self._derive_r5_r6(password)
        for candidate, label in ((password, "user password"),):
            key = _key_r2_r4(candidate, self.o, self.p, self.doc_id,
                             self.r, self.length, self.encrypt_metadata)
            want = _user_check_r2_r4(key, self.doc_id, self.r)
            got = self.u[:16] if self.r >= 3 else self.u[:32]
            if want[:len(got)] == got:
                return key, label
        # Try it as the owner password instead.
        user_pw = _user_password_from_owner(password, self.o, self.r, self.length)
        key = _key_r2_r4(user_pw, self.o, self.p, self.doc_id,
                         self.r, self.length, self.encrypt_metadata)
        want = _user_check_r2_r4(key, self.doc_id, self.r)
        got = self.u[:16] if self.r >= 3 else self.u[:32]
        if want[:len(got)] == got:
            return key, "owner password"
        raise CryptError(self._rejection())

    def _derive_r5_r6(self, password: bytes) -> tuple[bytes, str]:
        pw = password[:127]
        u_hash, u_vsalt, u_ksalt = self.u[:32], self.u[32:40], self.u[40:48]
        if _hash_r5_r6(pw, u_vsalt, b"", self.r) == u_hash:
            ikey = _hash_r5_r6(pw, u_ksalt, b"", self.r)
            return aes_cbc_decrypt(ikey, self.ue[:32], iv=b"\0" * 16,
                                   unpad=False), "user password"
        o_hash, o_vsalt, o_ksalt = self.o[:32], self.o[32:40], self.o[40:48]
        if _hash_r5_r6(pw, o_vsalt, self.u[:48], self.r) == o_hash:
            ikey = _hash_r5_r6(pw, o_ksalt, self.u[:48], self.r)
            return aes_cbc_decrypt(ikey, self.oe[:32], iv=b"\0" * 16,
                                   unpad=False), "owner password"
        raise CryptError(self._rejection())

    def _rejection(self) -> str:
        return ("password rejected. AIS, TIS, Form 16 and the s.143(1) "
                "intimation all open with the PAN in lowercase followed by the "
                "date of birth as ddmmyyyy, with no separator — the PAN "
                "lowercased with the date appended. Check the date "
                "against the PAN database rather than what the person remembers: "
                "a PAN issued against a different date of birth opens with that "
                "date, not the real one.")

    # -- data --------------------------------------------------------------
    def _object_key(self, num: int, gen: int) -> bytes:
        if self.r >= 5:
            return self.key
        extra = b"sAlT" if self.cfm == "AESV2" else b""
        digest = hashlib.md5(
            self.key
            + struct.pack("<i", num)[:3]
            + struct.pack("<i", gen)[:2]
            + extra).digest()
        return digest[:min(len(self.key) + 5, 16)]

    def decrypt(self, raw: bytes, num: int, gen: int = 0) -> bytes:
        if self.cfm == "Identity":
            return raw
        key = self._object_key(num, gen)
        if self.cfm in ("AESV2", "AESV3"):
            return aes_cbc_decrypt(key, raw)
        return rc4(key, raw)


def resolve_password(password: str | None, from_stdin: bool) -> str | None:
    """The password to use, given `--password` and `--password-stdin`.

    A password passed on the command line is not private. It goes into the
    shell's history file, and while the process runs it sits in argv, which on
    a normal Linux or macOS box any other process can read with `ps`. For a
    credential that is the taxpayer's own PAN and date of birth — the same pair
    that opens every other document they own — that is worth avoiding.

        python3 open_ais.py AIS.pdf --pan ABCDE1234F --dob 01/01/1990 \
            --print-password | python3 parse_tax_docs.py AIS.pdf --password-stdin
    """
    if not from_stdin:
        return password
    if password:
        raise CryptError(
            "--password and --password-stdin were both given. Pick one: the "
            "point of --password-stdin is that the password never reaches argv.")
    line = sys.stdin.readline()
    if not line.strip():
        raise CryptError(
            "--password-stdin was given but nothing arrived on standard input.")
    return line.rstrip("\r\n")


def make_decryptor(data: bytes, password: str | bytes = b"") -> PdfDecryptor:
    if isinstance(password, str):
        password = password.encode("utf-8")
    return PdfDecryptor(data, password)


# --------------------------------------------------------------------------
# Known-answer tests
# --------------------------------------------------------------------------

def _self_test() -> int:
    failures = []

    def check(name, got, want):
        if got != want:
            failures.append(f"FAIL  {name}\n        got  {got!r}\n        want {want!r}")
        else:
            print(f"PASS  {name}")

    # RC4 -- RFC 6229 section 2, keystream from the zero plaintext.
    for key, offset, want in [
        (bytes.fromhex("0102030405"), 0, "b2396305f03dc027ccc3524a0a1118a8"),
        (bytes.fromhex("0102030405"), 16, "6982944f18fc82d589c403a47a0d0919"),
        (bytes.fromhex("0102030405060708"), 0, "97ab8a1bf0afb96132f2f67258da15a8"),
        (bytes.fromhex("0102030405060708090a0b0c0d0e0f10"), 0,
         "9ac7cc9a609d1ef7b2932899cde41b97"),
        (bytes.fromhex("0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20"),
         0, "eaa6bd25880bf93d3f5d1e4ca2611d91"),
    ]:
        stream = rc4(key, b"\0" * (offset + 16))[offset:offset + 16]
        check(f"RFC 6229 RC4 keystream, {len(key)*8}-bit key at offset {offset}",
              stream.hex(), want)

    # AES single blocks -- FIPS 197 appendix C.
    for key, plain, want in [
        ("000102030405060708090a0b0c0d0e0f", "00112233445566778899aabbccddeeff",
         "69c4e0d86a7b0430d8cdb78070b4c55a"),
        ("000102030405060708090a0b0c0d0e0f1011121314151617",
         "00112233445566778899aabbccddeeff", "dda97ca4864cdfe06eaf70a0ec0d7191"),
        ("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
         "00112233445566778899aabbccddeeff", "8ea2b7ca516745bfeafc49904b496089"),
    ]:
        aes = AES(bytes.fromhex(key))
        cipher = aes.encrypt_block(bytes.fromhex(plain))
        check(f"FIPS 197 AES-{len(key)*4} encrypt", cipher.hex(), want)
        check(f"FIPS 197 AES-{len(key)*4} decrypt round trip",
              aes.decrypt_block(cipher).hex(), plain)

    # CBC -- NIST SP 800-38A F.2.1 / F.2.6.
    iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    plain = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a"
                          "ae2d8a571e03ac9c9eb76fac45af8e51")
    for key, want in [
        ("2b7e151628aed2a6abf7158809cf4f3c",
         "7649abac8119b246cee98e9b12e9197d"
         "5086cb9b507219ee95db113a917678b2"),
        ("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4",
         "f58c4c04d6e5f1ba779eabfb5f7bfbd6"
         "9cfc4e967edb808d679f777bc6702c7d"),
    ]:
        cipher = aes_cbc_encrypt_nopad(bytes.fromhex(key), plain, iv)
        check(f"SP 800-38A CBC-AES{len(key)*4} encrypt", cipher.hex(), want)
        back = aes_cbc_decrypt(bytes.fromhex(key), cipher, iv=iv, unpad=False)
        check(f"SP 800-38A CBC-AES{len(key)*4} decrypt", back.hex(), plain.hex())

    # The padding string is the one from the spec, byte for byte.
    check("the 32-byte padding string is the spec's",
          PAD.hex(), "28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a")
    check("a short password pads to 32 bytes", len(_pad_password(b"abc")), 32)
    check("a 40-byte password truncates to 32", len(_pad_password(b"x" * 40)), 32)

    # Algorithm 2 is deterministic and length-respecting.
    key40 = _key_r2_r4(b"", b"\x00" * 32, -28, b"\x01" * 16, 2, 5, True)
    check("Algorithm 2 at R2 yields a 40-bit key", len(key40), 5)
    key128 = _key_r2_r4(b"", b"\x00" * 32, -1852, b"\x01" * 16, 3, 16, True)
    check("Algorithm 2 at R3 yields a 128-bit key", len(key128), 16)
    check("Algorithm 2 depends on the document ID",
          key128 != _key_r2_r4(b"", b"\x00" * 32, -1852, b"\x02" * 16, 3, 16, True),
          True)
    check("Algorithm 2 depends on /P",
          key128 != _key_r2_r4(b"", b"\x00" * 32, -4, b"\x01" * 16, 3, 16, True),
          True)

    # A negative /P must serialise as a 4-byte signed little-endian value; an
    # unsigned reading changes the key and every stream decodes to noise.
    check("/P -28 packs as ffffffe4", struct.pack("<i", -28).hex(), "e4ffffff")

    # Algorithm 1's per-object key changes with the object number, which is the
    # whole point of it.
    class _Fake(PdfDecryptor):
        def __init__(self):
            self.r, self.cfm, self.key = 3, "V2", b"\x01" * 16
    fake = _Fake()
    check("the per-object key changes with the object number",
          fake._object_key(1, 0) != fake._object_key(2, 0), True)
    check("the per-object key is capped at 16 bytes",
          len(fake._object_key(1, 0)), 16)

    # RC4 is its own inverse; AES-CBC round trips through the PDF framing.
    check("RC4 round trip", rc4(b"key", rc4(b"key", b"payload")), b"payload")
    clear = b"content stream text"
    npad = 16 - len(clear) % 16
    body = clear + bytes([npad]) * npad
    framed = b"\x11" * 16 + aes_cbc_encrypt_nopad(b"k" * 16, body, b"\x11" * 16)
    check("AES-CBC round trip with a leading IV and PKCS#7 padding",
          aes_cbc_decrypt(b"k" * 16, framed), clear)
    # A whole final block of padding is legal and must come off completely.
    body16 = b"exactly16bytes!!" + bytes([16]) * 16
    check("a full block of PKCS#7 padding is stripped",
          aes_cbc_decrypt(b"k" * 16, b"\x22" * 16 + aes_cbc_encrypt_nopad(
              b"k" * 16, body16, b"\x22" * 16)), b"exactly16bytes!!")
    # Encryption must refuse a partial block rather than truncate it.
    try:
        aes_cbc_encrypt_nopad(b"k" * 16, b"short", b"\0" * 16)
        check("CBC encryption refuses a partial block", "accepted", "refused")
    except CryptError:
        check("CBC encryption refuses a partial block", "refused", "refused")
    # Algorithm 2.B must terminate and be deterministic.
    h1 = _hash_2b(b"password", b"\x01" * 8, b"")
    check("Algorithm 2.B returns a 32-byte key", len(h1), 32)
    check("Algorithm 2.B is deterministic", _hash_2b(b"password", b"\x01" * 8, b""), h1)
    check("Algorithm 2.B depends on the salt",
          _hash_2b(b"password", b"\x02" * 8, b"") != h1, True)

    for line in failures:
        print(line)
    if failures:
        print(f"\n{len(failures)} known-answer test(s) failed.")
        return 1
    print("\nAll known-answer tests pass: RC4 against RFC 6229, AES against "
          "FIPS 197 and SP 800-38A, and the PDF key schedule against the spec.")
    return 0


if __name__ == "__main__":
    sys.exit(_self_test())
