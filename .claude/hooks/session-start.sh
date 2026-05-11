#!/usr/bin/env bash
# SessionStart hook for Claude Code on the web.
#
# Installs project + dev dependencies so ruff, mypy, and pytest are usable
# during the agent loop. Runs synchronously by default so the agent can rely
# on tools being available from the first turn.

set -euo pipefail

# Only run inside the Claude Code web sandbox; locally, devs install however
# they like.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Editable install with dev extras. --user keeps installs in /root/.local
# without needing root or a venv; pip's cache is preserved across sessions.
pip install --user --quiet --root-user-action=ignore --upgrade pip
pip install --user --quiet --root-user-action=ignore -e '.[dev]'

# Ensure the user-bin dir is on PATH for this and future hook stages.
export PATH="$HOME/.local/bin:$PATH"
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
fi
