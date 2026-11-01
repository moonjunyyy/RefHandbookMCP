"""The vaults (portal/vault.py): a person's markdown directories, read and written through the service,
with an index for search and links; and what root would stage for it (refhandbook/agents/mounts.py)."""
import os

import pytest
from .conftest import SITE
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from portal import tokens
from portal.config import Settings
from portal.vault import Registry, VaultError, clean, create_app
from refhandbook.agents import mounts

ISS = "https://www.m00nny.kr"
JSON = {"Content-Type": "application/json"}


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def home(tmp_path):
    """alice's storage, with a vault in it as Obsidian leaves one."""
    v = tmp_path / "data" / "alice" / "Obsidian" / "Research"
    (v / ".obsidian").mkdir(parents=True)
    (v / ".obsidian" / "app.json").write_text("{}")
    (v / "Home.md").write_text("# Home\n\nStart at [[Ideas/Operators]] and [[Lie algebras|the algebras]]. #math\n")
    (v / "Ideas").mkdir()
    (v / "Ideas" / "Operators.md").write_text("# Operators\n\nAn operator $T$ on the chain. See [[Home]] and [[Missing note]]. #math #draft\n")
    (v / "Lie algebras.md").write_text("The algebras: $[x, y]$, a bracket. Back to [[Ideas/Operators#Chain]].\n")
    (v / "Ideas" / "figure.png").write_bytes(b"\x89PNG\r\n\x1a\n...")
    (v / "notes.txt").write_text("plain text\n")
    (tmp_path / "data" / "bob").mkdir()
    return tmp_path


@pytest.fixture
def client(tmp_path, key, home):
    s = Settings(session_secret="x" * 40, audit_log=str(tmp_path / "a.log"), sso_issuer=ISS, site_file=str(SITE))
    return TestClient(create_app(s, Registry(":memory:"), key.public_key(), roots=f"{home}/data/{{user}}=storage",
                                 data_dir=str(tmp_path / "state")))


def as_user(key, uid="alice", aud="vault"):
    return {"X-Auth-Token": tokens.issue(key, ISS, aud, uid)}


def register(client, h, path, name="Research"):
    return client.post("/vault/api/v1/vaults", headers={**h, **JSON}, json={"path": path, "name": name})


def test_paths_inside_a_vault_are_clean():
    assert clean("Ideas/Operators.md") == "Ideas/Operators.md" and clean("/Ideas//x.md/") == "Ideas/x.md"
    for bad in ("", "../x.md", "a/../b.md", ".obsidian/app.json", "a/.hidden.md", "a\0b"):
        with pytest.raises(VaultError):
            clean(bad)


def test_a_person_registers_a_directory_of_their_storage(client, key, home):
    alice, bob = as_user(key), as_user(key, "bob")
    assert client.get("/vault/api/v1/vaults").status_code == 401
    assert client.get("/vault/api/v1/vaults", headers=as_user(key, aud="calendar")).status_code == 401
    r = client.get("/vault/api/v1/vaults", headers=alice).json()
    assert r["vaults"] == [] and r["roots"] == [f"{home}/data/alice"]
    r = register(client, alice, f"{home}/data/alice/Obsidian/Research")
    assert r.status_code == 201 and r.json()["status"] == "ok" and r.json()["name"] == "Research"
    vid = r.json()["id"]
    assert register(client, alice, f"{home}/data/alice/Obsidian/Research").status_code == 409  # once
    assert register(client, alice, f"{home}/data/bob").status_code == 400  # not hers to register
    assert register(client, alice, "/etc").status_code == 400
    assert register(client, alice, "storage/Obsidian/../..").status_code == 400
    gone = register(client, alice, "storage/Nowhere").json()
    assert gone["status"] != "ok"  # registered, but there is no such directory
    assert client.get(f"/vault/api/v1/vaults/{gone['id']}/tree", headers=alice).status_code == 404
    assert [v["id"] for v in client.get("/vault/api/v1/vaults", headers=bob).json()["vaults"]] == []
    assert client.get(f"/vault/api/v1/vaults/{vid}/tree", headers=bob).status_code == 404
    assert client.delete(f"/vault/api/v1/vaults/{vid}", headers=bob).status_code == 404
    assert client.delete(f"/vault/api/v1/vaults/{vid}", headers=alice).status_code == 204
    assert (home / "data" / "alice" / "Obsidian" / "Research" / "Home.md").exists()  # the files stay


def test_the_tree_the_notes_and_the_attachments(client, key, home):
    alice = as_user(key)
    vid = register(client, alice, "storage/Obsidian/Research").json()["id"]
    tree = client.get(f"/vault/api/v1/vaults/{vid}/tree", headers=alice).json()
    names = {(c["path"], c["type"]) for c in tree["children"]}
    assert names == {("Home.md", "note"), ("Lie algebras.md", "note"), ("notes.txt", "text"), ("Ideas", "dir")}  # .obsidian hidden
    ideas = next(c for c in tree["children"] if c["path"] == "Ideas")
    assert {(c["path"], c["type"]) for c in ideas["children"]} == {("Ideas/Operators.md", "note"), ("Ideas/figure.png", "file")}
    note = client.get(f"/vault/api/v1/vaults/{vid}/file?path=Ideas/Operators.md", headers=alice).json()
    assert note["text"].startswith("# Operators") and len(note["sha256"]) == 64 and note["size"] > 0
    assert client.get(f"/vault/api/v1/vaults/{vid}/file?path=Ideas/figure.png", headers=alice).status_code == 415
    assert client.get(f"/vault/api/v1/vaults/{vid}/file?path=Nope.md", headers=alice).status_code == 404
    assert client.get(f"/vault/api/v1/vaults/{vid}/file?path=../../bob/x.md", headers=alice).status_code == 400
    assert client.get(f"/vault/api/v1/vaults/{vid}/file?path=.obsidian/app.json", headers=alice).status_code == 400
    raw = client.get(f"/vault/api/v1/vaults/{vid}/raw?path=Ideas/figure.png", headers=alice)
    assert raw.status_code == 200 and raw.headers["content-type"] == "image/png" and raw.content.startswith(b"\x89PNG")
    # a symlink leading out of the vault is refused
    os.symlink("/etc/hostname", home / "data" / "alice" / "Obsidian" / "Research" / "out.md")
    assert client.get(f"/vault/api/v1/vaults/{vid}/file?path=out.md", headers=alice).status_code == 400


def test_writes_are_guarded_by_the_hash_they_read(client, key, home):
    alice = as_user(key)
    vid = register(client, alice, "storage/Obsidian/Research").json()["id"]
    url = f"/vault/api/v1/vaults/{vid}/file?path=Home.md"
    note = client.get(url, headers=alice).json()
    # without the hash an existing note is not overwritten; with a stale one neither
    assert client.put(url, headers={**alice, **JSON}, json={"text": "x"}).status_code == 409
    assert client.put(url, headers={**alice, **JSON, "If-Match": "0" * 64}, json={"text": "x"}).status_code == 412
    r = client.put(url, headers={**alice, **JSON, "If-Match": note["sha256"]}, json={"text": "# Home\n\nchanged\n"})
    assert r.status_code == 200 and r.json()["sha256"] != note["sha256"]
    assert (home / "data" / "alice" / "Obsidian" / "Research" / "Home.md").read_text() == "# Home\n\nchanged\n"
    # a new note needs no hash, and makes its folders; a hash for a note that is not there is a 412
    new = f"/vault/api/v1/vaults/{vid}/file?path=Daily/2026-11-02.md"
    assert client.put(new, headers={**alice, **JSON, "If-Match": note["sha256"]}, json={"text": "x"}).status_code == 412
    assert client.put(new, headers={**alice, **JSON}, json={"text": "- [ ] write\n"}).status_code == 200
    assert (home / "data" / "alice" / "Obsidian" / "Research" / "Daily" / "2026-11-02.md").read_text() == "- [ ] write\n"
    assert client.put(new, headers={**alice, "Content-Type": "text/plain"}, content="x").status_code == 415
    assert client.put(f"/vault/api/v1/vaults/{vid}/file?path=Ideas/figure.png", headers={**alice, **JSON}, json={"text": "x"}).status_code == 415
    assert client.put(f"/vault/api/v1/vaults/{vid}/file?path=a.md", headers={**alice, **JSON}, json={"text": 5}).status_code == 400
    # move, and to the trash
    r = client.post(f"/vault/api/v1/vaults/{vid}/move", headers={**alice, **JSON}, json={"from": "Daily/2026-11-02.md", "to": "Daily/today.md"})
    assert r.status_code == 200 and (home / "data" / "alice" / "Obsidian" / "Research" / "Daily" / "today.md").exists()
    assert client.post(f"/vault/api/v1/vaults/{vid}/move", headers={**alice, **JSON}, json={"from": "Daily/today.md", "to": "Home.md"}).status_code == 409
    r = client.delete(f"/vault/api/v1/vaults/{vid}/file?path=Daily/today.md", headers=alice)
    assert r.status_code == 200 and r.json()["trash"] == ".trash/Daily/today.md"
    assert (home / "data" / "alice" / "Obsidian" / "Research" / ".trash" / "Daily" / "today.md").exists()
    assert client.delete(f"/vault/api/v1/vaults/{vid}/file?path=Daily/today.md", headers=alice).status_code == 404
    tree = client.get(f"/vault/api/v1/vaults/{vid}/tree", headers=alice).json()
    assert ".trash" not in {c["name"] for c in tree["children"]}


def test_search_links_backlinks_recent_and_tags(client, key, home):
    alice = as_user(key)
    vid = register(client, alice, "storage/Obsidian/Research").json()["id"]
    hits = client.get(f"/vault/api/v1/vaults/{vid}/search?q=bracket", headers=alice).json()["hits"]
    assert [h["path"] for h in hits] == ["Lie algebras.md"] and "[bracket]" in hits[0]["snippet"]
    assert {h["path"] for h in client.get(f"/vault/api/v1/vaults/{vid}/search?q=oper", headers=alice).json()["hits"]} == {"Ideas/Operators.md", "Home.md", "Lie algebras.md"}  # the links name it too
    assert client.get(f"/vault/api/v1/vaults/{vid}/search?q=", headers=alice).json()["hits"] == []
    assert client.get(f"/vault/api/v1/vaults/{vid}/search?q=%22unbalanced", headers=alice).status_code == 200
    links = client.get(f"/vault/api/v1/vaults/{vid}/links?path=Home.md", headers=alice).json()
    assert links["links"] == [{"path": "Ideas/Operators.md", "text": "Ideas/Operators"}, {"path": "Lie algebras.md", "text": "Lie algebras"}]
    assert links["backlinks"] == ["Ideas/Operators.md"]
    ops = client.get(f"/vault/api/v1/vaults/{vid}/links?path=Ideas/Operators.md", headers=alice).json()
    assert ops["links"] == [{"path": "Home.md", "text": "Home"}, {"path": None, "text": "Missing note"}]
    assert ops["backlinks"] == ["Home.md", "Lie algebras.md"]  # a heading link and a path link both count
    tags = client.get(f"/vault/api/v1/vaults/{vid}/tags", headers=alice).json()["tags"]
    assert tags == [{"tag": "math", "notes": 2}, {"tag": "draft", "notes": 1}]
    # a change is seen on the next look: the note is recent, its new link counts
    url = f"/vault/api/v1/vaults/{vid}/file?path=Lie algebras.md"
    h = client.get(url, headers=alice).json()["sha256"]
    client.put(url, headers={**alice, **JSON, "If-Match": h}, json={"text": "Now about [[Home]] only.\n"})
    recent = client.get(f"/vault/api/v1/vaults/{vid}/recent?n=2", headers=alice).json()["notes"]
    assert recent[0]["path"] == "Lie algebras.md" and len(recent) == 2
    assert client.get(f"/vault/api/v1/vaults/{vid}/links?path=Home.md", headers=alice).json()["backlinks"] == ["Ideas/Operators.md", "Lie algebras.md"]
    assert [h["path"] for h in client.get(f"/vault/api/v1/vaults/{vid}/search?q=bracket", headers=alice).json()["hits"]] == []


def test_root_stages_what_people_registered(tmp_path):
    """The reconciler reads the vault registry (--picks vault) and plans the same idmapped stage as for
    the handbook's policy mounts: a registered directory of theirs, under an offered root."""
    reg = Registry(str(tmp_path / "state" / "vault.db"))
    (tmp_path / "data" / "alice" / "Research").mkdir(parents=True)
    reg.add("alice", "Research", str(tmp_path / "data" / "alice" / "Research"))
    reg.add("alice", "Nowhere", str(tmp_path / "data" / "alice" / "Nowhere"))
    reg.add("bob", "Research", str(tmp_path / "data" / "bob" / "Research"))
    picks = mounts.vault_picks(tmp_path / "state")
    assert picks == [("alice", [(str(tmp_path / "data" / "alice" / "Nowhere"), True), (str(tmp_path / "data" / "alice" / "Research"), True)]),
                     ("bob", [(str(tmp_path / "data" / "bob" / "Research"), True)])]
    import pwd

    me = pwd.getpwuid(os.getuid())

    def getpw(user):
        if user != "alice":
            raise KeyError(user)
        return pwd.struct_passwd((user, "x", me.pw_uid, me.pw_gid, "", "/", "/bin/sh"))

    p = mounts.plan(tmp_path / "state", tmp_path / "stage", 999, mounts.parse(f"{tmp_path}/data/{{user}}=storage"),
                    min_uid=0, getpw=getpw, picks=mounts.vault_picks)
    assert [s.host for s in p.stages] == [str((tmp_path / "data" / "alice" / "Research").resolve())]
    assert p.status["alice"][str(tmp_path / "data" / "alice" / "Nowhere")].endswith("does not exist")
    assert p.skipped == ["bob: no such account"]
    assert mounts.vault_picks(tmp_path / "nothing") == []
