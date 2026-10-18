"""Translate /etc/nslcd.conf into the remote server's RHB_LDAP_* settings.

Standard library only: root runs it before the service environment exists
(nslcd.conf is usually readable by root alone).
"""

from __future__ import annotations


def env_from_nslcd(text: str) -> tuple[list[str], list[str]]:
    """Translate /etc/nslcd.conf into RHB_LDAP_* lines. Returns (env lines, notes).

    The bind password is never copied: write it to a root-only file and point
    RHB_LDAP_BIND_PASSWORD_FILE at it.
    """
    uris: list[str] = []
    kv: dict[str, str] = {}
    bases: dict[str, str] = {}
    filters: dict[str, str] = {}
    uid_attr = "uid"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition(" ")
        v = v.strip()
        if k == "uri":
            uris += v.split()
        elif k == "base":
            parts = v.split(None, 1)
            if len(parts) == 2 and "=" not in parts[0]:
                bases[parts[0]] = parts[1]
            else:
                bases[""] = v
        elif k == "filter":
            m, _, f = v.partition(" ")
            filters[m] = f.strip()
        elif k == "map":
            parts = v.split()
            if len(parts) == 3 and parts[0] == "passwd" and parts[1] == "uid":
                uid_attr = parts[2]
        else:
            kv[k] = v
    out: list[str] = []
    notes: list[str] = []
    if uris:
        out.append(f"RHB_LDAP_URI={uris[0]}")
        if uris[0].startswith("ldapi:"):
            notes.append("nslcd uses a local socket (ldapi); if sign-in reports the directory unavailable, "
                         "set RHB_LDAP_URI=ldap://localhost (with RHB_LDAP_STARTTLS=1 if slapd offers it)")
        if len(uris) > 1:
            notes.append(f"nslcd lists {len(uris)} URIs; only the first is used: {uris[0]}")
    ssl_mode = kv.get("ssl", "off").lower()
    if ssl_mode == "start_tls":
        out.append("RHB_LDAP_STARTTLS=1")
    if kv.get("tls_cacertfile"):
        out.append(f"RHB_LDAP_CA_FILE={kv['tls_cacertfile']}")
    if kv.get("tls_reqcert", "").lower() in ("never", "allow"):
        notes.append("nslcd does not verify the LDAP certificate (tls_reqcert); this server always does: "
                      "set RHB_LDAP_CA_FILE to the CA that signed it")
    base = bases.get("passwd") or bases.get("")
    if base:
        out.append(f"RHB_LDAP_USER_BASE={base}")
    flt = filters.get("passwd", "(objectClass=posixAccount)")
    out.append(f"RHB_LDAP_USER_FILTER=(&{flt}({uid_attr}={{uid}}))")
    if bases.get("group"):
        out.append(f"RHB_LDAP_GROUP_BASE={bases['group']}")
    if kv.get("binddn"):
        out.append(f"RHB_LDAP_BIND_DN={kv['binddn']}")
        if kv.get("bindpw"):
            out.append("RHB_LDAP_BIND_PASSWORD_FILE=/etc/refhandbook/ldap-bindpw")
            notes.append("copy nslcd's bindpw into /etc/refhandbook/ldap-bindpw (mode 0400, owner refhandbook); "
                         "it is not printed here")
    else:
        notes.append("nslcd binds anonymously; this server will search anonymously too")
    if uid_attr != "uid":
        notes.append(f"nslcd maps uid to {uid_attr}; the per-user database is named after that value")
    return out, notes
