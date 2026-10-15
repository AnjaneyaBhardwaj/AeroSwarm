#!/bin/bash
# SessionStart hook for Claude Code on the web: install Python deps and a
# headless-safe XFoil so `make test` / `make demo` work in fresh containers.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

# Python deps (uv sync reuses the cached .venv when the container is cached).
uv sync --quiet

# XFoil built from the Ubuntu source package without FP traps (idempotent).
scripts/install_xfoil.sh /usr/local

# OpenFOAM v1912 (Ubuntu package) for the T2 tier, swarm/solvers/openfoam (idempotent). The OpenFOAM image
# and package hosts are blocked by this environment's network policy; the Ubuntu archive is not.
if ! command -v simpleFoam >/dev/null 2>&1; then
  { DEBIAN_FRONTEND=noninteractive apt-get install -y -q openfoam >/dev/null 2>&1 \
    || { apt-get update -q >/dev/null 2>&1 && DEBIAN_FRONTEND=noninteractive apt-get install -y -q openfoam >/dev/null 2>&1; }; } \
    || echo "session-start: OpenFOAM install failed; T2 (of2d) evaluations will report openfoam_missing" >&2
fi
