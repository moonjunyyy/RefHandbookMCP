# SMB passwords: the site's password is the SMB password (src/portal/ntlm.py)

An account's password lives in Kerberos. An SMB client that holds a ticket for the realm could use it
alone, but one that types a password (most phone apps, Windows outside the realm) logs in with NTLM: a
challenge-response that Samba checks with the account's **NT hash**, MD4 of the password in UTF-16LE
(MS-NLMP, NTOWFv1). The password never crosses the wire and no other store can check it for Samba, so
the hash has to sit where Samba reads it. Kerberos keeps only its own keys and discards the password, so
the hash can only be made where the password is known, when it is set: here, on the site.

So, with SMB passwords on, every password the site sets in Kerberos is written to the account's entry in
the directory as its NT hash, which Samba reads through its LDAP passdb (`ldapsam`):

| where the site sets a password | who writes the SMB side |
|---|---|
| an account made (by an admin, from a request, from an invitation) | the portal |
| one's own password changed (account page; the portal's own `/expired` without the sign-in) | the portal |
| a password reset by helpdesk or an admin | the portal |
| a one-time or expired password changed at the sign-in (`/auth/expired`) | the person (below) |
| an account disabled or enabled | the portal (the `D` flag) |

The SMB step comes after Kerberos has taken the change and never undoes it: when it fails, the audit log
records `smb_password` (or `smb_enable`) with the reason and the person or admin sees a warning beside
the result; the page or API answer carries it (`warning`).

## What is written

On the user's entry (`uid=<uid>,<users_ou>`), the first time: the auxiliary class `sambaSamAccount` and
its `sambaSID` — the domain's SID with the RID Samba's algorithmic mapping gives the uid
(`uid × 2 + base`, the base from the domain entry's `sambaAlgorithmicRidBase`); a SID another entry
holds is refused. Every time: `sambaNTPassword` (32 hex digits, upper case, as Samba writes it),
`sambaPwdLastSet`, and no `sambaLMPassword`. `sambaAcctFlags` is `[U          ]` (normal), with `D`
while the account is disabled. Samba's domain entry is `sambaDomainName=<workgroup>,<base_dn>`
(`workgroup`: the realm's first label, uppercased, unless `[site] workgroup` says otherwise).

The sign-in holds no LDAP identity of its own (it is the most exposed piece). On its expired-password
page it gets a ticket with the new password and writes the person's own hash as them, so the
directory lets a person write — never read — their own `sambaNTPassword` and `sambaPwdLastSet`. The
cost: a person can set their own SMB hash through LDAP directly; only their own.

## The rules (slapd-acl.ldif)

| attributes of a user's entry | portal | Samba's DN | the person | others |
|---|---|---|---|---|
| `sambaNTPassword`, `sambaLMPassword`, `sambaPasswordHistory` | write only | read | write only | none |
| `sambaPwdLastSet` | write | read | write | read |
| `sambaSID`, `sambaPrimaryGroupSID`, `sambaDomainName` | write | read | read | read |
| what Samba keeps up (`sambaAcctFlags`, logon and bad-password times and counts, …) | write | write | read | read |

They come after the rule for the account's own attributes (first match wins, attribute by attribute,
so `uid` and `cn` stay under theirs) and before the catch-all. Samba's DN reads the hash and cannot
write it: an SMB client cannot change a password behind Kerberos. The domain entry: Samba's DN writes
(its RID counters), everyone signed in reads.

## On the host, once

The installer renders `/etc/<name>/directory/samba.ldif` (the steps, in its header, and the domain
entry with the Samba host's SID from `net getlocalsid`) and `smb-passdb.conf` (the `[global]` lines);
in order: Samba's schema and its indexes; the rules; the Samba DN (`uid=samba,ou=Services,<base_dn>`
unless `[site] samba_dn`) with a password only Samba keeps (`smbpasswd -w`); the domain entry; the
`smb.conf` lines (`passdb backend = ldapsam:ldapi:///` unless `[site] samba_ldap_uri`); then
`smb_passwords = "1"` in `[site]` of the site file (or `PORTAL_SMB_PASSWORDS=1` for both the portal and
the sign-in) and the installer again.

## Limits

- A password changed **outside the site** (`kpasswd`, `kadmin.local`) does not reach SMB: the account
  keeps its old SMB password until the site sets one. Only kadmind sees such a change (its
  `kadm5_hook` plugin gets the new password), which would be a plugin on the KDC, not this site.
- **Accounts from before** (today's `tdbsam` ones) get their SMB password in the directory the first time
  the site sets their password; until then Samba, reading the directory, has none for them. An admin's
  reset, or the person changing it once, does it.
- The hash is MD4, unsalted: anyone who reads it can log in over SMB as that account. Hence the rules
  above, and the hash goes only over the directory's encrypted connections (LDAPS, or the local socket).
