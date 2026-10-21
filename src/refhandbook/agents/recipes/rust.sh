# Rust stable through rustup: toolchains under /opt/rust; at run time cargo's home is /work/.cargo.
set -eu
arch=$(uname -m)
mkdir -p /opt/rust
python3 /recipes/fetch.py "https://static.rust-lang.org/rustup/dist/${arch}-unknown-linux-gnu/rustup-init" /opt/rust/rustup-init
chmod 755 /opt/rust/rustup-init
RUSTUP_HOME=/opt/rust/rustup CARGO_HOME=/opt/rust/cargo /opt/rust/rustup-init -y --no-modify-path \
  --profile minimal --default-toolchain stable
rm -f /opt/rust/rustup-init
RUSTUP_HOME=/opt/rust/rustup /opt/rust/cargo/bin/rustc --version
