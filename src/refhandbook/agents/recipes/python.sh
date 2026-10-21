# uv, and a uv-managed CPython under /opt/python, linked into /usr/local/bin.
# (/tmp is noexec in a build: what runs is unpacked where the layer keeps it.)
set -eu
arch=$(uname -m)
python3 /recipes/fetch.py --unpack \
  "https://github.com/astral-sh/uv/releases/latest/download/uv-${arch}-unknown-linux-gnu.tar.gz" /usr/local/bin 1
UV_PYTHON_INSTALL_DIR=/opt/python UV_PYTHON_BIN_DIR=/opt/python/bin /usr/local/bin/uv python install 3.13
py=$(ls -d /opt/python/cpython-3.13*/bin/python3.13 | head -n1)
for n in python python3 python3.13; do ln -sf "$py" "/usr/local/bin/$n"; done
rm -rf /opt/python/bin
/usr/local/bin/python3 -c "import sys, ssl; print(sys.version)"
