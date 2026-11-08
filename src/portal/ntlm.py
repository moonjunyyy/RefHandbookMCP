"""SMB passwords: what Samba keeps for an account, computed from a password the site sets.

An SMB client that types a password logs in with NTLM, a challenge-response that Samba checks with the
account's NT hash: MD4 of the password in UTF-16LE (MS-NLMP NTOWFv1). Samba reads it from the account's
LDAP entry (passdb backend ldapsam: the sambaSamAccount class), and only the site sees the password when
it is set, so the site writes the hash then (docs/smb.md).

What is written follows Samba's own encodings (source3/include/passdb.h, source3/passdb/passdb.c):
the account flags as pdb_encode_acct_ctrl writes them, a user's RID as its algorithmic mapping of the
uid gives it.

Standard library only. MD4 is written out here (RFC 1320): OpenSSL 3 keeps it in its legacy provider,
so hashlib may not have it.
"""

from __future__ import annotations

import struct

ACCOUNT_CLASS = "sambaSamAccount"  # a user entry Samba can use
DOMAIN_CLASS = "sambaDomain"  # the domain entry: its SID and the algorithmic RID base

# passdb.h: RID_MULTIPLIER (a user's RID = uid * RID_MULTIPLIER + base; USER_RID_TYPE adds 0) and
# NEW_PW_FORMAT_SPACE_PADDED_LEN (the flags' buffer: '[', the letters, spaces, ']' and the C string's end)
RID_MULTIPLIER = 2
FLAGS_LEN = 14
# pdb_encode_acct_ctrl's order of the letters: N no password required, D disabled, H home directory
# required, T temporary duplicate, U normal user, M MNS logon, W workstation trust, S server trust,
# L auto-locked, X password does not expire, I interdomain trust
FLAG_ORDER = "NDHTUMWSLXI"
NORMAL, DISABLED = "U", "D"

_MASK = 0xFFFFFFFF


def _rotl(v: int, s: int) -> int:
    v &= _MASK
    return ((v << s) | (v >> (32 - s))) & _MASK


# RFC 1320 3.4: the three rounds — the auxiliary function, the added constant, the order of the block's
# words and the four shifts
_ROUNDS = (
    (lambda x, y, z: (x & y) | (~x & z), 0, tuple(range(16)), (3, 7, 11, 19)),
    (lambda x, y, z: (x & y) | (x & z) | (y & z), 0x5A827999,
     (0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15), (3, 5, 9, 13)),
    (lambda x, y, z: x ^ y ^ z, 0x6ED9EBA1,
     (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15), (3, 9, 11, 15)),
)
_INIT = (0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476)


def md4(data: bytes) -> bytes:
    """The MD4 digest of `data` (RFC 1320)."""
    msg = bytearray(data)
    msg.append(0x80)
    msg.extend(b"\0" * ((56 - len(msg)) % 64))
    msg.extend(struct.pack("<Q", (8 * len(data)) & 0xFFFFFFFFFFFFFFFF))
    state = list(_INIT)
    for off in range(0, len(msg), 64):
        x = struct.unpack("<16I", msg[off:off + 64])
        before = list(state)
        for fn, const, order, shifts in _ROUNDS:
            for i, k in enumerate(order):
                j = -i % 4  # the register this step sets: a, d, c, b, a, …; the other three follow it
                b, c, d = state[(j + 1) % 4], state[(j + 2) % 4], state[(j + 3) % 4]
                state[j] = _rotl(state[j] + fn(b, c, d) + x[k] + const, shifts[i % 4])
        state = [(s + t) & _MASK for s, t in zip(state, before)]
    return struct.pack("<4I", *state)


def nt_hash(password: str) -> str:
    """The NT hash of a password as Samba stores it (sambaNTPassword): 32 hex digits, upper case."""
    return md4(password.encode("utf-16-le")).hex().upper()


def decode_flags(value: str) -> set[str]:
    """The letters of an account-flags value ('[DU         ]' → {'D', 'U'})."""
    return {c for c in value.strip().strip("[]") if c in FLAG_ORDER}


def encode_flags(letters: set[str]) -> str:
    """Account flags as pdb_encode_acct_ctrl writes them: '[U          ]'."""
    inner = "".join(c for c in FLAG_ORDER if c in letters)
    return "[" + inner.ljust(FLAGS_LEN - 3) + "]"


def flags_with(value: str, disabled: bool) -> str:
    """An account's flags (empty: a normal account's) with the disabled letter set or cleared."""
    letters = decode_flags(value) or {NORMAL}
    return encode_flags(letters | {DISABLED} if disabled else letters - {DISABLED})


def user_rid(uid_number: int, base: int) -> int:
    """The RID Samba's algorithmic mapping gives a unix uid."""
    return uid_number * RID_MULTIPLIER + base
