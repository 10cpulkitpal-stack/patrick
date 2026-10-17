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

if [[ "$("${NODE_HOME}/bin/node" --version)" != "v${NODE_VERSION}" ]]; then
  echo "Expected Node.js v${NODE_VERSION} in ${NODE_HOME}" >&2
  exit 1
fi

PACKAGE_MANAGER="$("${NODE_HOME}/bin/node" -p "require('${ROOT_DIR}/frontend/package.json').packageManager")"
if [[ "${PACKAGE_MANAGER}" != "pnpm@${PNPM_VERSION}" ]]; then
  echo "render-build.sh pins pnpm@${PNPM_VERSION}, but frontend/package.json declares ${PACKAGE_MANAGER}" >&2
  exit 1
fi

python -m pip install -r "${ROOT_DIR}/requirements.txt"
"${NODE_HOME}/bin/npm" install --global --prefix "${NODE_HOME}" "pnpm@${PNPM_VERSION}"
if [[ "$("${NODE_HOME}/bin/pnpm" --version)" != "${PNPM_VERSION}" ]]; then
  echo "Failed to install pinned pnpm@${PNPM_VERSION}" >&2
  exit 1
fi
cd "${ROOT_DIR}/frontend"
"${NODE_HOME}/bin/pnpm" install --frozen-lockfile
"${NODE_HOME}/bin/pnpm" build
if [[ ! -s "${ROOT_DIR}/frontend/out/index.html" ]]; then
  echo "Frontend build did not create frontend/out/index.html" >&2
  exit 1
fi
