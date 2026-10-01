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
