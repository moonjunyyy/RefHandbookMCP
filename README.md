# ldap-portal

Self-service and admin web portal for a Kerberos realm: OpenLDAP (`ldaps://ldap.<realm>`)
with MIT Kerberos 1.22 storing principals in LDAP (kldap).

- **Every user**: sign in with their Kerberos password, edit display name, email and login shell,
  change their password, and set a new one when it has expired.
- **Helpdesk** (`cn=helpdesk` group): search users, reset passwords (one-time password that must be
  changed at next sign-in), unlock after failed logins. Never on admins or protected groups.
- **Admin** (`cn=admin` group): all of the above, plus create users, disable/enable, manage groups,
  approve or reject account requests, and make invitation links.
- **The site's other services**: the menu links every app of the site file
  (`deploy/site.toml`) that has a menu label and that the user's groups may see, such as
  refhandbook's approval page `/agents` (rule proposals, sandbox policies, jobs).
- **Anyone** (no account yet): ask for one at `/request` ("사용 신청"): a username, what it is for,
  and optionally a name and email, with a consent notice for the personal data. The request waits
  for an admin; nothing is created until then.
- **Anyone with an invitation link**: open it, choose a username and a password, and the account
  exists at once (`/join/<token>`).

Creating a user follows the existing layout: `uid=<u>,ou=Users` (inetOrgPerson, posixAccount,
shadowAccount), a private group `cn=<u>,ou=Groups` with gid = uid number, membership in `cn=user`,
then `kadmin addprinc -x dn=<entry> <u>/user` plus the alias `<u>@<REALM>`. If Kerberos fails, the
LDAP entries are rolled back. Name and email are optional; without a name, `cn`/`sn` (required by
inetOrgPerson) hold the username. The name is not copied into `gecos`, which every host shows to
every user through NSS (`PORTAL_WRITE_GECOS=1` brings that back for ASCII names).

## Security model

Each permission is enforced in three places, so a bug or a compromise in the web app is contained:

| Layer | Enforces | File |
|---|---|---|
| Portal (app) | who sees which page/button; helpdesk vs admin; no self-lockout | `portal/rbac.py` |
| kadmind | which principals the portal's service identity may add/reset/modify | `deploy/kadm5.acl` |
| slapd | which entries/attributes the portal may write; key material hidden | `deploy/slapd-acl.ldif` |

Other protections:
- Passwords live only in Kerberos. The portal never stores, logs, or writes password hashes, and
  never passes a password on a command line (kadmin/kpasswd are driven through a pty).
- Login verification gets a ticket for `HTTP/<domain>` and decrypts it with the portal's
  keytab, which blocks KDC-spoofing attacks against password checks.
- Admins never pick passwords: resets and new accounts get a random one-time password with
  `+needchange`.
- The portal service principal is `portal/service`, deliberately not `*/admin`, since the default
  `kadm5.acl` gives `*/admin` every privilege.
- LDAPS with certificate validation; HTTPS-only `SameSite=Strict` session cookies; CSRF tokens on
  every form; strict input validation before anything reaches a DN or a kadmin query; login
  throttling (plus Kerberos lockout policy); CSP and other security headers; `Cache-Control: no-store`.
- Roles and the disabled flag are re-read from LDAP on every request: disabling a user or removing
  them from `admin` takes effect immediately, not when their session expires.
- Every login and change goes to a JSON-lines audit log (who, what, target, IP).

### Permission matrix

| Action | user | helpdesk | admin |
|---|---|---|---|
| Edit own profile (name, mail, shell), change own password | ✓ | ✓ | ✓ |
| List/search users | | ✓ | ✓ |
| Reset password / unlock (non-admin targets) | | ✓ | ✓ |
| Reset password / unlock an admin | | | ✓ |
| Create user, disable/enable, add/remove groups | | | ✓ |
| Approve/reject account requests | | | ✓ |
| Reset, disable, or change groups of your own account | ✗ | ✗ | ✗ |

To change who can do what: add or remove people from `cn=admin` / `cn=helpdesk` in LDAP (or from the
portal's Groups card). To change what a role can do, edit `PERMISSIONS` in `portal/rbac.py`, and
loosen the matching `kadm5.acl`/olcAccess lines if needed.

## Setup

One command installs or updates everything, and is rerun after any change (code, `deploy/site.toml`,
templates). Nothing on the host is named by hand: every name and path derives from the Kerberos
realm (krb5.conf's `default_realm`) and `deploy/site.toml` (`portal/facts.py`).

```sh
sudo deploy/install.sh --check     # what it derives, before touching anything
sudo deploy/install.sh             # install or update
```

| derived | from the realm `EXAMPLE.ORG` | override in `[site]` |
|---|---|---|
| site name | `example` | `name` |
| domain | `www.example.org` | `domain` |
| LDAP | `ldaps://ldap.example.org`, `dc=example,dc=org`, `ou=Users,…`, `ou=Groups,…` | `ldap_uri`, `base_dn`, `users_ou`, `groups_ou` |
| services | `example-portal` (:8080), `example-sso` (:8090) | `ports` |
| TLS | nginx, with `/etc/letsencrypt/live/<domain>` | `router` (and `listen`), below |
| each service's | system user, `/etc/<unit>`, `/var/lib/<unit>`, `/var/log/<unit>` | |
| code | `/opt/example-portal` (with its `.venv`) | `code` |

What the installer does: creates the two service users; copies the code and builds its virtualenv;
installs `deploy/site.toml` as `/etc/<name>/site.toml`; renders the systemd units, the nginx site and
snippets, and the directory's side (below) from `deploy/templates/`; makes each
service's env file once with a fresh secret (`/etc/<unit>/{portal,sso}.env`: secrets and local
overrides only, never overwritten) and the SSO's token key pair; then `nginx -t`, enables and
restarts the units. A host on the old layout (unit `ldap-portal`) is moved: the old unit is removed
and its `/etc`, `/var/lib`, `/var/log` carried over to the derived names. The WebDAV directory timer
(`dav-homes`, `<site>-dav-homes`) of earlier versions is stopped and removed; `/data` is left as it is.

### TLS at a router

With a TLS-terminating proxy in front (a router holding a DNS-challenged certificate, say), name it
in `[site]`: `router = "192.168.0.1"` (an address or CIDR, or a list: the router's address as
this host sees it, so its inside interface). Keep it out of the repository by putting it in
`deploy/site.local.toml` (git-ignored; its `[site]` keys win over `site.toml`'s, and it is installed
beside it). nginx then serves plain HTTP
on `listen` (80) and:
- answers only the router (and localhost); anyone else reaching the port directly gets 403;
- takes the client from the router's `X-Forwarded-For` (`set_real_ip_from`), so the sign-in rate
  limits and the audit log see clients, not the router;
- still redirects the aliases to `https://<domain>`, and still sends HSTS.

The apps need nothing else: cookies stay `Secure` (the browser sees https) and the backends are
told `X-Forwarded-Proto: https`. The installer renders the router's side into
`/etc/<name>/router/<domain>.conf`: `Host` and `X-Forwarded-For` passed on, the site's 4m body
limit, and no buffering with long timeouts for `/mcp`'s streamed answers.

It ends with what only an admin can do, as exact commands for this site: the keytabs it could not
find, and where the rendered directory files are.

### The directory's side (once, on the KDC and the LDAP server)

The installer renders both files into `/etc/<name>/directory/` with this realm's names, DNs and the
current members of the admin group; re-render (rerun the installer) after adding an admin.

- `kadm5.acl`: merge into `/etc/krb5kdc/kadm5.acl` above any broader rule, then restart
  `krb5-admin-server`. It denies the portal every principal it must never touch, including each
  admin's everyday principals.
- `slapd-acl.ldif`: merge with the current `olcAccess` (instructions inside). Rule `{0}` keeps
  Kerberos key material away from users: before it, an ordinary GSSAPI bind could read
  `krbPrincipalKey` on its own entry, and a `(krbPrincipalKey=*)` search matched `krbtgt/<REALM>`.
  Check from an ordinary account afterwards that `ldapsearch -Y GSSAPI … krbPrincipalKey` on the
  krbtgt entry prints nothing.
- The portal's policy and principals: `kadmin -q 'addpol -minlength 12 -minclasses 3 -history 5
  -maxfailure 5 -failurecountinterval 15m -lockoutduration 15m users'`, and `addprinc -randkey
  portal/service` and `addprinc -randkey HTTP/<domain>` (the installer prints the `ktadd` lines).
- `slapo-unique` on `uidNumber` and `gidNumber` (the portal's ID allocation lock is per-process);
  optionally the `accesslog` overlay; a `helpdesk` group.
- `PORTAL_SASL_USERPASSWORD=1` (in the portal's env file) gives new users `userPassword:
  {SASL}<uid>/user@<REALM>`, so LDAP simple binds go through saslauthd to Kerberos; only with
  saslauthd running `-a kerberos5`.

Run the portal on a host only admins can log in to: anyone with root there holds its kadmin keytab.

### Tests

```sh
uv pip install --python .venv/bin/python -e '.[dev]' && .venv/bin/python -m pytest -q
```

The tests run the real app (routes, permissions, CSRF, throttling, rollback, first-login password
change) against in-memory fakes of LDAP and Kerberos.

### Account requests ("사용 신청")

`/request` is public. A request is stored in `PORTAL_REQUESTS_DB` (SQLite, mode 0600 under
`/var/lib/<site>-portal`), not in LDAP, so the portal needs no new directory rights for it. Admins see
the queue under **Requests** and approve (the normal create-user path; the one-time password is
shown once, to be passed on over a separate channel) or reject. Either way the request row is deleted
at once; unanswered ones go after `PORTAL_REQUEST_TTL_DAYS` (30). The audit log records the username
and the decision, not the name or email.

Abuse limits: 5 submissions per address per hour, at most `PORTAL_REQUEST_MAX_PENDING` (100) waiting,
and the page answers the same whether or not a username is taken, so it cannot be used to list
accounts. Set `PORTAL_REQUESTS=0` to turn it off.

### Invitations (가입 링크)

An admin makes a one-time link under **Invite** (with a note of whom it is for) and sends it. Whoever
opens it chooses a username and a password and has an account at once: the normal create-user path,
but with the password they chose and no forced change, so there is no one-time password to pass
on. The link works once (it is claimed before the account is made, and put back if making it fails)
and expires after `PORTAL_INVITE_TTL_HOURS` (168); admins can revoke open ones. Only the token's
hash is stored (`PORTAL_INVITES_DB`, mode 0600 under `/var/lib/<site>-portal`), so the database alone
cannot be used to sign up. The page tells the link's holder whether a username is taken (it has to);
without a valid link it says nothing. Failed sign-ups are limited to 10 per address per hour, on top
of nginx's `login` rate. The link points at `PORTAL_PUBLIC_URL` (`https://<domain>`). Set
`PORTAL_INVITES=0` to turn it off.

### Personal data (개인정보)

Name and email are personal data. What the portal does about it:
- Collects only username and purpose as required; name and email are optional and say what they are for.
- Shows a consent notice (items, purpose, retention, the right to refuse) and requires agreement
  before a request is accepted. Set `PORTAL_PRIVACY_CONTACT` to name who answers questions about it.
- Deletes request data as soon as it is decided, or after the TTL.
- Keeps names out of `gecos`, and rule `{4}` in `deploy/slapd-acl.ldif` makes `cn`, `sn`,
  `givenName`, `displayName`, `mail`, `gecos` (and the other contact attributes) readable only by
  the user and the portal. Before that rule, every signed-in account could read every user's name
  and email with `ldapsearch`, and `getent passwd` showed the gecos name on every host.

Existing entries still carry `gecos` copied from the name. Once the ACL is in place, remove it
(check the LDIF before applying it):

```sh
kinit <you>/admin
ldapsearch -Q -LLL -o ldif-wrap=no -Y GSSAPI -H ldaps://ldap.<realm> -b ou=Users,<base_dn> '(gecos=*)' dn \
  | awk '/^dn:/{print; print "changetype: modify"; print "delete: gecos"; print ""}' > strip-gecos.ldif
ldapmodify -Q -Y GSSAPI -H ldaps://ldap.<realm> -f strip-gecos.ldif
```

Check from an ordinary account afterwards: `ldapsearch -Y GSSAPI ... -b ou=Users,<base_dn> mail cn`
should list only your own values, and `getent passwd <someone-else>` should have an empty fifth field.

### Serving under a sub-path

Set `PORTAL_ROOT_PATH=/account` and proxy `/account/` to the portal (the second half of
`deploy/nginx.conf`). Links, redirects and the session cookie's `Path` all carry the prefix, and the
app accepts requests whether or not nginx strips it.

## One sign-in for the site

The site runs behind one nginx server with one Kerberos sign-in:

| Path | What | Who checks |
|---|---|---|
| `/` | main page, `portal/sso.py`: sign-in or a greeting, and a card per app of the site file | public |
| `/auth/` | site sign-in, `portal/sso.py` on :8090 | public (rate-limited) |
| `/account/` | this portal on :8080 with `PORTAL_AUTH=sso`; `/account/request` and `/account/join/` stay public | `auth_request` + token |
| `/agents` | refhandbook's approval page | `auth_request` + token |
| `/mcp`, `/authorize`, `/token`, `/register`, `/revoke`, `/login`, `/.well-known/oauth-*` | refhandbook with `RHB_AUTH=sso` | its own OAuth; `/login` via `auth_request` + token |

**Services are declared, not hand-wired.** `deploy/site.toml` lists every service once: its
routes, the audience its tokens are minted for, its card on the main page and its menu entry
(`portal/site.py`). The installer renders from it the nginx snippets (the audience map and the
locations, included by the site's nginx config, which keeps only TLS, the main page and the
sign-in); the SSO shows its cards on the main page and mints tokens for the audiences the file
declares, and the portal's menu shows its apps. The renderer refuses duplicate routes, unknown fields and limits, and
routes with nowhere to go; a `site` route goes through the sign-in and carries a token only for its
own app, and a `public` route clears any token header. Adding a service: one `[[app]]` in
`deploy/site.toml`, then `sudo deploy/install.sh`.

**Apps the site hosts.** A browser app (a built `dist/`, such as 글타래) needs no server of its
own: an `[[app]]` with `static = true` is served at `/apps/<id>/` behind the sign-in, and with
`storage = true` each user gets a JSON store next to it, `/apps/<id>/api/store/<key>`
(`portal/apps.py`, the `<site>-apps` unit), so what they save follows their account. Tokens for it
are minted for the app's id alone, and the store checks the app in the path against them: one app's
token does not open another's data. Publish a build with `sudo deploy/install.sh --app <id> <dist>`.
An app built with relative paths (Vite `base: './'`) finds its store at `api/` next to its page.

How it fits together:
- nginx asks the SSO (`/auth/check`) before every protected request. A browser is known by the
  site cookie (`<site>_sso`, `Path=/`, `SameSite=Lax`, 8 h from sign-in); without one, nginx sends
  it to `/auth/login?next=...`. One-time and expired passwords are changed at `/auth/expired`.
- Backends never trust a user header. For `/account/`, `/agents` and `/login`, nginx names the backend
  (`map $request_uri $auth_audience`) and the SSO answers with `X-Auth-Token`: an EdDSA JWT for
  that backend only, valid one minute (`portal/tokens.py`). Backends hold the public key alone, so a
  local user who reaches :8080 or :8765 directly cannot forge one, and a token for one backend is
  refused by the other.
- refhandbook keeps its OAuth (Claude needs the metadata, registration, PKCE and `/token`); only
  its sign-in step is replaced: signed in to the site, `/login` just asks "allow Claude as <uid>?".
- The SSO runs as its own user with only the `HTTP/<domain>` keytab and the signing key; the
  portal's kadmin keytab never meets the most exposed process.

It is all installed by `sudo deploy/install.sh` (Setup, above).

Check: `/account/` while signed out redirects to `/auth/login`.

## Not included (on purpose)

- **Deleting users.** Disable instead. Deleting frees the uidNumber, which could later be reused
  and inherit the old user's files. Delete by hand: `kadmin delprinc`, then `ldapdelete`.
- **Open self-registration.** Anyone on the network could create accounts. Sign-up takes an admin's
  invitation link, or a request an admin approves.
- **Sending email.** The portal never mails one-time passwords; the admin passes them on.
- **File sharing.** WebDAV was here once; files are shared over SMB instead, outside this site.
- **2FA for admin actions.** Recommended: put the portal behind an SSO with MFA, or require
  Kerberos OTP/PKINIT for members of `admin`.
