"""Input validation. Everything that reaches LDAP DNs or kadmin queries passes through here."""
import re
import secrets
import string

from .i18n import t

UID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
GROUP_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
EMAIL_RE = re.compile(r"^[^@\s,;\"<>]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
RESERVED_UIDS = {"root", "admin", "kadmin", "krbtgt", "kdc", "portal", "nobody", "daemon", "bin", "sys"}
# A project's name is a group's, a share's and a path's: not a role group, not an SMB section name.
RESERVED_PROJECTS = RESERVED_UIDS | {"user", "users", "admins", "helpdesk", "global", "homes", "printers",
                                     "project", "projects", "group", "groups", "public", "share", "shares",
                                     "join", "new"}  # paths of the projects' pages and API
JOIN_POLICIES = ("open", "request", "invite")


class ValidationError(ValueError):
    pass


def uid(value: str) -> str:
    value = value.strip()
    if not UID_RE.fullmatch(value):
        raise ValidationError(t("사용자명: 영문 소문자로 시작하는 2–32자 (소문자, 숫자, '-', '_')."))
    return value


def new_uid(value: str) -> str:
    value = uid(value)
    if value in RESERVED_UIDS:
        raise ValidationError(t("쓸 수 없는 사용자명입니다."))
    return value


def group(value: str) -> str:
    value = value.strip()
    if not GROUP_RE.fullmatch(value):
        raise ValidationError(t("그룹 이름이 올바르지 않습니다."))
    return value


def project_name(value: str) -> str:
    value = group(value)
    if value in RESERVED_PROJECTS:
        raise ValidationError(t("쓸 수 없는 프로젝트 이름입니다."))
    return value


def description(value: str) -> str:
    value = " ".join(value.replace("\r\n", "\n").split(" ")).strip()
    if len(value) > 500 or "\x00" in value:
        raise ValidationError(t("설명: 500자까지 쓸 수 있습니다."))
    return value


def join_policy(value: str) -> str:
    if value not in JOIN_POLICIES:
        raise ValidationError(t("가입 방식이 올바르지 않습니다."))
    return value


def name(value: str, label: str) -> str:
    value = " ".join(value.split())
    if not value or len(value) > 64 or any(c in value for c in "\x00<>\"\\"):
        raise ValidationError(t("{label}: 1–64자, < > \" 와 역슬래시는 쓸 수 없습니다.", label=label))
    return value


def optional_name(value: str, label: str) -> str:
    return name(value, label) if value.strip() else ""


def purpose(value: str) -> str:
    value = value.strip().replace("\r\n", "\n")
    if not value or len(value) > 500 or "\x00" in value:
        raise ValidationError(t("사용 목적: 1–500자로 적어 주세요."))
    return value


def email(value: str) -> str:
    value = value.strip()
    if value and (len(value) > 254 or not EMAIL_RE.fullmatch(value)):
        raise ValidationError(t("이메일 주소가 올바르지 않습니다."))
    return value


def shell(value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValidationError(t("고를 수 없는 셸입니다."))
    return value


def new_password(value: str, confirm: str) -> str:
    if value != confirm:
        raise ValidationError(t("새 비밀번호 두 칸이 다릅니다."))
    if len(value) < 12:
        raise ValidationError(t("비밀번호는 12자 이상이어야 합니다."))
    if len(value) > 256 or "\n" in value or "\r" in value:
        raise ValidationError(t("비밀번호에 쓸 수 없는 문자가 있습니다."))
    return value


def temp_password(length: int = 16) -> str:
    """Random one-time password with every character class, for admin resets."""
    alphabet = string.ascii_letters + string.digits + "-_.!@#%"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(c in "-_.!@#%" for c in pw)):
            return pw
