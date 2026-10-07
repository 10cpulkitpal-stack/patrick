#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NODE_VERSION="22.14.0"
PNPM_VERSION="11.19.0"
NODE_HOME="${TMPDIR:-/tmp}/patrick-node-${NODE_VERSION}"

# The existing Render service uses Python, so install a pinned Node runtime in
# the build environment to produce the same-origin static Next.js frontend.
if [[ ! -x "${NODE_HOME}/bin/node" ]]; then
  mkdir -p "${NODE_HOME}"
  curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
    | tar -xJ --strip-components=1 -C "${NODE_HOME}"
fi
export PATH="${NODE_HOME}/bin:${PATH}"

python -m pip install -r "${ROOT_DIR}/requirements.txt"
"${NODE_HOME}/bin/npm" install --global --prefix "${NODE_HOME}" "pnpm@${PNPM_VERSION}"
cd "${ROOT_DIR}/frontend"
"${NODE_HOME}/bin/pnpm" install --frozen-lockfile
"${NODE_HOME}/bin/pnpm" build
