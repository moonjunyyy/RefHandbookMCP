"""Each user's own API keys, sealed so that only the runner can open them (docs/agents.md §2).

A key is sealed to an X25519 public key: an ephemeral key pair, ECDH, HKDF-SHA256, AES-256-GCM,
with `uid|provider|label` as associated data (a row moved to another user or provider does not
open). The web process holds only the public key (RHB_AGENT_KEYS_PUB); the runner reads the private
key from its systemd credential (`$CREDENTIALS_DIRECTORY/agent-keys`) or RHB_AGENT_KEYS_FILE.

Rows live in `<data>/agent-keys.db`. The model never sees a key: tools list providers, labels and
fingerprints only, and the runner scrubs a key out of any error text before it goes anywhere.
"""

from __future__ import annotations

import base64
import os
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PROVIDERS = ("anthropic", "openai", "gemini")
LABEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
INFO = b"refhandbook agent key v1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    uid         TEXT NOT NULL,
    provider    TEXT NOT NULL,
    label       TEXT NOT NULL,
    epk         BLOB NOT NULL,
    nonce       BLOB NOT NULL,
    ct          BLOB NOT NULL,
    fingerprint TEXT NOT NULL,
    created     REAL NOT NULL,
    last_used   REAL,
    status      TEXT NOT NULL DEFAULT 'ok',
    PRIMARY KEY (uid, provider, label)
);
"""


class KeyError_(ValueError):
    pass


def fingerprint(secret: str) -> str:
    s = secret.strip()
    return f"{s[:6]}…{s[-4:]}" if len(s) > 12 else "…" + s[-2:]


def _aad(uid: str, provider: str, label: str) -> bytes:
    return f"{uid}|{provider}|{label}".encode()


def _kdf(shared: bytes, epk: bytes, rpk: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=epk + rpk, info=INFO).derive(shared)


def _raw_pub(pub: X25519PublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def seal(pub: X25519PublicKey, secret: str, aad: bytes) -> tuple[bytes, bytes, bytes]:
    eph = X25519PrivateKey.generate()
    epk = _raw_pub(eph.public_key())
    key = _kdf(eph.exchange(pub), epk, _raw_pub(pub))
    nonce = os.urandom(12)
    return epk, nonce, AESGCM(key).encrypt(nonce, secret.encode(), aad)


def unseal(priv: X25519PrivateKey, epk: bytes, nonce: bytes, ct: bytes, aad: bytes) -> str:
    key = _kdf(priv.exchange(X25519PublicKey.from_public_bytes(epk)), epk, _raw_pub(priv.public_key()))
    return AESGCM(key).decrypt(nonce, ct, aad).decode()


def generate(priv_path: str | Path, pub_path: str | Path) -> None:
    """Make the key pair (install.sh): the private key 0400, the public key 0444."""
    priv = X25519PrivateKey.generate()
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    pub = priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    fd = os.open(priv_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    Path(pub_path).write_bytes(pub)
    os.chmod(pub_path, 0o444)


def load_public(path: str | Path | None = None) -> X25519PublicKey:
    p = Path(path or os.environ.get("RHB_AGENT_KEYS_PUB", "/etc/refhandbook/agent-keys.pub"))
    k = serialization.load_pem_public_key(p.read_bytes())
    if not isinstance(k, X25519PublicKey):
        raise KeyError_(f"{p} is not an X25519 public key")
    return k


def private_path() -> Path:
    cred = os.environ.get("CREDENTIALS_DIRECTORY")
    if cred and (Path(cred) / "agent-keys").exists():
        return Path(cred) / "agent-keys"
    return Path(os.environ.get("RHB_AGENT_KEYS_FILE", "/etc/refhandbook/agent-keys"))


def load_private(path: str | Path | None = None) -> X25519PrivateKey:
    k = serialization.load_pem_private_key(Path(path or private_path()).read_bytes(), password=None)
    if not isinstance(k, X25519PrivateKey):
        raise KeyError_("the agent key file is not an X25519 private key")
    return k


@dataclass
class KeyInfo:
    provider: str
    label: str
    fingerprint: str
    created: float
    last_used: float | None
    status: str


class KeyStore:
    """The sealed rows. `put` needs only the public key; `get` needs the private key."""

    def __init__(self, path: str | Path, public: X25519PublicKey | None = None,
                 private: X25519PrivateKey | None = None):
        self.path = str(path)
        self.public = public
        self.private = private
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, uid: str, provider: str, label: str, secret: str) -> KeyInfo:
        if provider not in PROVIDERS:
            raise KeyError_(f"provider: {', '.join(PROVIDERS)}")
        if not LABEL_RE.match(label):
            raise KeyError_("label: letters, digits, '.', '_' and '-', at most 32")
        secret = secret.strip()
        if len(secret) < 8 or len(secret) > 512 or any(c.isspace() for c in secret):
            raise KeyError_("that does not look like an API key")
        if self.public is None:
            raise KeyError_("no public key configured (RHB_AGENT_KEYS_PUB)")
        epk, nonce, ct = seal(self.public, secret, _aad(uid, provider, label))
        fp = fingerprint(secret)
        now = time.time()
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO api_keys (uid, provider, label, epk, nonce, ct, fingerprint, created,"
                       " status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok')", (uid, provider, label, epk, nonce, ct, fp, now))
        return KeyInfo(provider, label, fp, now, None, "ok")

    def list(self, uid: str) -> list[KeyInfo]:
        with self._db() as db:
            rows = db.execute("SELECT provider, label, fingerprint, created, last_used, status FROM api_keys"
                              " WHERE uid = ? ORDER BY provider, label", (uid,)).fetchall()
        return [KeyInfo(*r) for r in rows]

    def delete(self, uid: str, provider: str, label: str) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM api_keys WHERE uid = ? AND provider = ? AND label = ?",
                              (uid, provider, label)).rowcount > 0

    def get(self, uid: str, provider: str, label: str | None = None) -> str:
        """The plaintext key (runner only). With no label, the user's first key for the provider."""
        if self.private is None:
            raise KeyError_("this process cannot open keys")
        with self._db() as db:
            if label:
                row = db.execute("SELECT label, epk, nonce, ct FROM api_keys WHERE uid = ? AND provider = ? AND label = ?",
                                 (uid, provider, label)).fetchone()
            else:
                row = db.execute("SELECT label, epk, nonce, ct FROM api_keys WHERE uid = ? AND provider = ?"
                                 " ORDER BY label LIMIT 1", (uid, provider)).fetchone()
            if row is None:
                raise KeyError_(f"no {provider} key{' ' + label if label else ''} registered for {uid}")
            db.execute("UPDATE api_keys SET last_used = ? WHERE uid = ? AND provider = ? AND label = ?",
                       (time.time(), uid, provider, row[0]))
        return unseal(self.private, row[1], row[2], row[3], _aad(uid, provider, row[0]))

    def mark(self, uid: str, provider: str, label: str, status: str) -> None:
        with self._db() as db:
            db.execute("UPDATE api_keys SET status = ? WHERE uid = ? AND provider = ? AND label = ?",
                       (status, uid, provider, label))


def scrub(text: str, secrets: list[str]) -> str:
    """Remove secrets (and their url-encoded / base64 forms) from text that may leave the runner."""
    for s in secrets:
        if not s:
            continue
        for form in {s, base64.b64encode(s.encode()).decode()}:
            text = text.replace(form, "[key]")
    return text
