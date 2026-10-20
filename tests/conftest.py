"""The tests run as the m00nny site (the realm the fakes use); every other fact derives from it."""
import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("PORTAL_REALM", "M00NNY.KR")

# The repository's site file, copied alone: a host's deploy/site.local.toml must not change the tests.
SITE = Path(tempfile.mkdtemp(prefix="site-")) / "site.toml"
shutil.copy(Path(__file__).parent.parent / "deploy" / "site.toml", SITE)
