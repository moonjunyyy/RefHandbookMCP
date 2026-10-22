"""Input validation. Everything that reaches LDAP DNs or kadmin queries passes through here."""
import re
import secrets
import string

UID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
GROUP_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
EMAIL_RE = re.compile(r"^[^@\s,;\"<>]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
RESERVED_UIDS = {"root", "admin", "kadmin", "krbtgt", "kdc", "portal", "nobody", "daemon", "bin", "sys"}


class ValidationError(ValueError):
    pass


def uid(value: str) -> str:
    value = value.strip()
    if not UID_RE.fullmatch(value):
        raise ValidationError("Username: 2–32 chars, lowercase letters, digits, '-' or '_', starting with a letter.")
    return value


def new_uid(value: str) -> str:
    value = uid(value)
    if value in RESERVED_UIDS:
        raise ValidationError("That username is reserved.")
    return value


def group(value: str) -> str:
    value = value.strip()
    if not GROUP_RE.fullmatch(value):
        raise ValidationError("Invalid group name.")
    return value


def name(value: str, label: str) -> str:
    value = " ".join(value.split())
    if not value or len(value) > 64 or any(c in value for c in "\x00<>\"\\"):
        raise ValidationError(f"{label}: 1–64 characters, no < > \" or backslash.")
    return value


def optional_name(value: str, label: str) -> str:
    return name(value, label) if value.strip() else ""


def purpose(value: str) -> str:
    value = value.strip().replace("\r\n", "\n")
    if not value or len(value) > 500 or "\x00" in value:
        raise ValidationError("사용 목적: 1–500자로 적어 주세요.")
    return value


def email(value: str) -> str:
    value = value.strip()
    if value and (len(value) > 254 or not EMAIL_RE.fullmatch(value)):
        raise ValidationError("Invalid email address.")
    return value


def shell(value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValidationError("Shell not allowed.")
    return value


def new_password(value: str, confirm: str) -> str:
    if value != confirm:
        raise ValidationError("New passwords do not match.")
    if len(value) < 12:
        raise ValidationError("Password must be at least 12 characters.")
    if len(value) > 256 or "\n" in value or "\r" in value:
        raise ValidationError("Password contains invalid characters.")
    return value


def temp_password(length: int = 16) -> str:
    """Random one-time password with every character class, for admin resets."""
    alphabet = string.ascii_letters + string.digits + "-_.!@#%"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(c in "-_.!@#%" for c in pw)):
            return pw
