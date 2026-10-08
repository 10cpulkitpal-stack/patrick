#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}/frontend"
pnpm build

if [[ ! -s "${ROOT_DIR}/frontend/out/index.html" ]]; then
  echo "Next.js static export did not create frontend/out/index.html" >&2
  exit 1
fi

# Vercel serves root public/ files as CDN-backed static assets. This folder is
# generated at build time and ignored by Git; keep the source export in frontend/out.
mkdir -p "${ROOT_DIR}/public"
cp -a "${ROOT_DIR}/frontend/out/." "${ROOT_DIR}/public/"

if [[ ! -s "${ROOT_DIR}/public/index.html" || ! -s "${ROOT_DIR}/public/signin.html" ]]; then
  echo "Vercel static output is missing the home or sign-in page" >&2
  exit 1
fi
