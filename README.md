# m00nny site

One site behind one Kerberos sign-in: the account portal, the reference handbook (an MCP server
Claude connects to), and small hosted apps. Everything about a host derives from its Kerberos realm
and one site file; one installer renders and installs it all.

```
pyproject.toml, uv.lock   one project, two packages
src/portal/               the site: facts (what derives from the realm), the site file, the
                          installer, the sign-in (SSO), the account portal, the apps' storage
src/refhandbook/          the handbook: MCP server (OAuth, consent after the site sign-in),
                          cards, research ledger, kernel, agents and their sandbox runner
web/                      the site's pages (TypeScript, vite): /, /account/…, /agents/… over the APIs
apps/                     hosted apps (static builds published at /apps/<id>/)
deploy/site.toml          the site file
deploy/templates/         every file the installer renders (units, nginx, env, directory ACLs)
deploy/install.sh         the installer
tests/portal, tests/refhandbook
docs/                     site.md (the site and portal), handbook.md, kernel.md, agents.md
```

```sh
sudo deploy/install.sh --check     # what it derives, before touching anything
sudo deploy/install.sh             # install or update everything
uv run pytest                      # both suites
cd web && npm ci && npm run build  # the pages (published by the installer)
```
