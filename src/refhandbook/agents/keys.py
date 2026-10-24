"""Each user's own API keys, sealed so that only the runner can open them (docs/agents.md §2).

A key is sealed to an X25519 public key: an ephemeral key pair, ECDH, HKDF-SHA256, AES-256-GCM,
with `uid|provider|label|format|base_url` as associated data: a row moved to another user or
provider does not open, and neither does one whose endpoint was rewritten (a custom key cannot be
redirected to another server by whoever can write the table).

Providers: anthropic, openai, gemini, and `custom`: any server that speaks one of the standard
formats (FORMATS: Anthropic Messages, OpenAI Responses, OpenAI Chat Completions, Gemini
generateContent) at a base URL of the user's. A custom key may be empty (a local server without
authentication). The web process holds only the public key; the runner reads the private key from its systemd
credential (`$CREDENTIALS_DIRECTORY/agent-keys`). Both default to the unit's configuration directory
(`$CONFIGURATION_DIRECTORY/agent-keys[.pub]`), where the installer makes the pair once:
`python -m refhandbook.agents.keys gen <dir>`; RHB_AGENT_KEYS_PUB and RHB_AGENT_KEYS_FILE override.

Rows live in `<data>/agent-keys.db`. The model never sees a key: tools list providers, labels and
fingerprints only, and the runner scrubs a key out of any error text before it goes anywhere.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PROVIDERS = ("anthropic", "openai", "gemini", "custom")
# the wire format each provider speaks; a custom key names its own
FORMATS = ("anthropic", "openai", "openai-chat", "gemini")
NATIVE_FORMAT = {"anthropic": "anthropic", "openai": "openai", "gemini": "gemini"}
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
    format      TEXT NOT NULL DEFAULT '',
    base_url    TEXT NOT NULL DEFAULT '',
    models      TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (uid, provider, label)
);
"""
# columns added after the first schema: (name, declaration)
LATER = (("format", "TEXT NOT NULL DEFAULT ''"), ("base_url", "TEXT NOT NULL DEFAULT ''"),
         ("models", "TEXT NOT NULL DEFAULT '[]'"))


class KeyError_(ValueError):
    pass


def fingerprint(secret: str) -> str:
    s = secret.strip()
    if not s:
        return "(없음)"
    return f"{s[:6]}…{s[-4:]}" if len(s) > 12 else "…" + s[-2:]


def _aad(uid: str, provider: str, label: str, fmt: str = "", base_url: str = "") -> bytes:
    return f"{uid}|{provider}|{label}|{fmt}|{base_url}".encode()


def check_base_url(url: str) -> str:
    """A custom endpoint's base URL as stored: http(s), a host, no credentials, query or fragment,
    no trailing slash. Whether its address may be reached is the runner's check, on every call
    (providers.endpoint_allowed), since a name can resolve differently later."""
    from urllib.parse import urlparse

    u = url.strip().rstrip("/")
    try:
        p = urlparse(u)
        p.port  # noqa: B018 — raises on a bad port
    except ValueError as e:
        raise KeyError_(f"base URL: {e}") from e
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password or p.query or p.fragment \
            or any(c.isspace() for c in u) or len(u) > 300:
        raise KeyError_("base URL: http(s)://host[:port][/path], without credentials, query or fragment")
    return u


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


def _conf(name: str) -> Path:
    """A file in the unit's configuration directory (systemd's ConfigurationDirectory=)."""
    d = os.environ.get("CONFIGURATION_DIRECTORY", "").split(":")[0]
    if not d:
        raise KeyError_(f"no {name}: not in a unit with ConfigurationDirectory=, and no RHB_AGENT_KEYS_* set")
    return Path(d) / name


def generate(priv_path: str | Path, pub_path: str | Path) -> None:
    """Make the key pair (the installer, once): the private key 0400, the public key 0444."""
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
    p = Path(path or os.environ.get("RHB_AGENT_KEYS_PUB") or _conf("agent-keys.pub"))
    k = serialization.load_pem_public_key(p.read_bytes())
    if not isinstance(k, X25519PublicKey):
        raise KeyError_(f"{p} is not an X25519 public key")
    return k


def private_path() -> Path:
    cred = os.environ.get("CREDENTIALS_DIRECTORY")
    if cred and (Path(cred) / "agent-keys").exists():
        return Path(cred) / "agent-keys"
    return Path(os.environ.get("RHB_AGENT_KEYS_FILE") or _conf("agent-keys"))


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
    format: str = ""
    base_url: str = ""
    models: list[str] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.provider}/{self.label}"


@dataclass
class Key:
    """An opened key, for one call (the runner's): never stored, logged or shown."""
    provider: str
    label: str
    secret: str = field(repr=False)
    format: str
    base_url: str


def split_ref(ref: str) -> tuple[str, str]:
    """'anthropic/main' → ('anthropic', 'main')."""
    provider, _, label = ref.partition("/")
    if provider not in PROVIDERS or not LABEL_RE.match(label):
        raise KeyError_(f"key {ref!r}: provider/label, provider one of {', '.join(PROVIDERS)}")
    return provider, label


class KeyStore:
    """The sealed rows. `put` needs only the public key; `get` needs the private key."""

    @classmethod
    def for_web(cls, data_dir: str | Path) -> KeyStore:
        """The web process's store: it seals with the public key when it has one, and opens nothing."""
        try:
            pub = load_public()
        except (KeyError_, OSError, ValueError):
            pub = None
        return cls(Path(data_dir) / "agent-keys.db", public=pub)

    def __init__(self, path: str | Path, public: X25519PublicKey | None = None,
                 private: X25519PrivateKey | None = None):
        self.path = str(path)
        self.public = public
        self.private = private
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)
            have = {r[1] for r in db.execute("PRAGMA table_info(api_keys)")}
            for name, decl in LATER:
                if name not in have:
                    db.execute(f"ALTER TABLE api_keys ADD COLUMN {name} {decl}")

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, uid: str, provider: str, label: str, secret: str, *, fmt: str = "", base_url: str = "",
            models: list[str] | None = None) -> KeyInfo:
        """Seal and store a key (replacing one of the same provider and label). A custom key names its
        format and base URL; the others speak their own format at their own endpoint."""
        if provider not in PROVIDERS:
            raise KeyError_(f"provider: {', '.join(PROVIDERS)}")
        if not LABEL_RE.match(label):
            raise KeyError_("label: letters, digits, '.', '_' and '-', at most 32")
        if provider == "custom":
            if fmt not in FORMATS:
                raise KeyError_(f"format: {', '.join(FORMATS)}")
            base_url = check_base_url(base_url)
        else:
            fmt, base_url = NATIVE_FORMAT[provider], ""
        secret = secret.strip()
        if any(c.isspace() for c in secret) or len(secret) > 512 or (
                (len(secret) < 8) and not (provider == "custom" and secret == "")):
            raise KeyError_("that does not look like an API key")
        if self.public is None:
            raise KeyError_("no public key configured (RHB_AGENT_KEYS_PUB)")
        epk, nonce, ct = seal(self.public, secret, _aad(uid, provider, label, fmt, base_url))
        fp = fingerprint(secret)
        now = time.time()
        ms = sorted(set(models or []))[:500]
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO api_keys (uid, provider, label, epk, nonce, ct, fingerprint, created,"
                       " status, format, base_url, models) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?, ?, ?)",
                       (uid, provider, label, epk, nonce, ct, fp, now, fmt, base_url, json.dumps(ms)))
        return KeyInfo(provider, label, fp, now, None, "ok", fmt, base_url, ms)

    def list(self, uid: str) -> list[KeyInfo]:
        with self._db() as db:
            rows = db.execute("SELECT provider, label, fingerprint, created, last_used, status, format, base_url,"
                              " models FROM api_keys WHERE uid = ? ORDER BY provider, label", (uid,)).fetchall()
        return [KeyInfo(*r[:8], json.loads(r[8] or "[]")) for r in rows]

    def info(self, uid: str, provider: str, label: str) -> KeyInfo | None:
        return next((k for k in self.list(uid) if (k.provider, k.label) == (provider, label)), None)

    def delete(self, uid: str, provider: str, label: str) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM api_keys WHERE uid = ? AND provider = ? AND label = ?",
                              (uid, provider, label)).rowcount > 0

    def get(self, uid: str, provider: str, label: str) -> Key:
        """The opened key (runner only)."""
        if self.private is None:
            raise KeyError_("this process cannot open keys")
        with self._db() as db:
            row = db.execute("SELECT epk, nonce, ct, format, base_url FROM api_keys WHERE uid = ? AND provider = ?"
                             " AND label = ?", (uid, provider, label)).fetchone()
            if row is None:
                raise KeyError_(f"no {provider} key {label!r} registered for {uid}")
            db.execute("UPDATE api_keys SET last_used = ? WHERE uid = ? AND provider = ? AND label = ?",
                       (time.time(), uid, provider, label))
        fmt, base = row[3] or NATIVE_FORMAT.get(provider, ""), row[4] or ""
        secret = unseal(self.private, row[0], row[1], row[2], _aad(uid, provider, label, fmt, base))
        return Key(provider, label, secret, fmt, base)

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


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "gen":
        d = Path(sys.argv[2])
        generate(d / "agent-keys", d / "agent-keys.pub")
        print(f"wrote {d}/agent-keys (0400) and {d}/agent-keys.pub (0444)")
    else:
        raise SystemExit("usage: python -m refhandbook.agents.keys gen <directory>")
