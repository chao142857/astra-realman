#!/usr/bin/env bash
# Fresh isolated runtime only. No global package changes, authentication or inference.
set -euo pipefail
LAB_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$LAB_DIR/../../.." && pwd)
if [[ $# != 1 ]]; then echo 'Usage: bootstrap_lab.sh /absolute/path/to/python3.10' >&2; exit 2; fi
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { echo 'Requires Linux x86_64' >&2; exit 2; }
[[ ! -e "$REPO_ROOT/.venv" && ! -e "$REPO_ROOT/.toolchain" ]] || { echo 'Refusing to overwrite an existing runtime' >&2; exit 2; }
"$1" -c 'import sys; assert sys.version_info[:2] == (3,10), "Locked runtime requires Python 3.10"'
"$1" -m venv "$REPO_ROOT/.venv"
"$REPO_ROOT/.venv/bin/python" -m pip install -r "$LAB_DIR/requirements.lock.txt"
mkdir -p "$REPO_ROOT/.toolchain/bin"
curl -fL --retry 0 --connect-timeout 15 --max-time 600 \
  'https://registry.npmjs.org/@openai/codex/-/codex-0.160.0-linux-x64.tgz' \
  -o "$REPO_ROOT/.toolchain/codex-0.160.0-linux-x64.tgz"
"$REPO_ROOT/.venv/bin/python" - "$REPO_ROOT/.toolchain/codex-0.160.0-linux-x64.tgz" <<'PY'
import hashlib,sys
from pathlib import Path
assert hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()=='37a41d61c3399182b8c727b77090cc7a1566bd849d0f09070a0bbc6fec4c58dc', 'CLI_PACKAGE_HASH'
PY
tar -xzf "$REPO_ROOT/.toolchain/codex-0.160.0-linux-x64.tgz" -C "$REPO_ROOT/.toolchain/bin" --strip-components=4 \
  package/vendor/x86_64-unknown-linux-musl/bin/codex \
  package/vendor/x86_64-unknown-linux-musl/bin/codex-code-mode-host
"$REPO_ROOT/.venv/bin/python" - "$REPO_ROOT" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);(root/'.toolchain/environment.json').write_text(json.dumps({'cli_executable':str(root/'.toolchain/bin/codex')},indent=2)+'\n')
PY
"$REPO_ROOT/.toolchain/bin/codex" --version
echo 'Isolated software installed; authentication unchanged; generation requests=0'
