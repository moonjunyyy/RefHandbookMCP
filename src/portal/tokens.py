"""Identity tokens the SSO hands to backends through nginx (X-Auth-Token).

A JWT signed with the SSO's Ed25519 key (EdDSA): `sub` is the uid, `aud` the backend it is for,
`exp` a minute out. Backends hold only the public key, so neither a local user nor a compromised
backend can mint one, and a token taken from one backend is refused by another.

Make a key pair (as root, on the host running the SSO):
    python -m portal.tokens genkey /etc/<site>-sso      (the installer does this once)
which writes sso-signing.pem (0600, give it to the SSO's user) and sso-public.pem (0644).
"""
import sys
import time
from pathlib import Path

import jwt

ALGORITHM = "EdDSA"
LEEWAY = 5  # seconds of clock skew tolerated between the SSO and a backend


class TokenError(Exception):
    pass


def load_private_key(path: str):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    return load_pem_private_key(Path(path).read_bytes(), password=None)


def load_public_key(path: str):
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    return load_pem_public_key(Path(path).read_bytes())


def issue(private_key, issuer: str, audience: str, uid: str, ttl: int = 60) -> str:
    now = int(time.time())
    return jwt.encode({"iss": issuer, "aud": audience, "sub": uid, "iat": now, "exp": now + ttl},
                      private_key, algorithm=ALGORITHM)


def verify(public_key, token: str, issuer: str, audience: str) -> str:
    """The uid in a valid token for `audience`; TokenError otherwise."""
    try:
        claims = jwt.decode(token, public_key, algorithms=[ALGORITHM], audience=audience, issuer=issuer,
                            leeway=LEEWAY, options={"require": ["exp", "iat", "sub", "aud", "iss"]})
    except jwt.PyJWTError as e:
        raise TokenError(str(e)) from e
    return str(claims["sub"])


def genkey(directory: str) -> None:
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    priv = d / "sso-signing.pem"
    if priv.exists():
        raise SystemExit(f"{priv} exists; remove it first to rotate the key")
    fd = os.open(priv, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    pub = d / "sso-public.pem"
    pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                  serialization.PublicFormat.SubjectPublicKeyInfo))
    pub.chmod(0o644)
    print(f"wrote {priv} (0600) and {pub} (0644)")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "genkey":
        genkey(sys.argv[2])
    else:
        raise SystemExit("usage: python -m portal.tokens genkey <directory>")
