#!/usr/bin/env bash
# Runs once after the Dev Container is created.
set -euo pipefail
cd /workspace

# Named volumes are created root-owned; hand them to the dev user.
sudo chown -R vscode:vscode /workspace/.venv /home/vscode/.cache /commandhistory \
  /home/vscode/.claude /home/vscode/.codex 2>/dev/null || true

uv sync
(cd apps/web && npm ci --no-audit --no-fund)
if [ -d .git ]; then uv run pre-commit install --install-hooks >/dev/null || true; fi
make migrate

cat <<'MSG'

Cairn Dev Container ready.
  make seed        # synthetic demo data (+ website sign-in accounts)
  make api         # API on :8000; then `make web` for the website on :5173
  make up          # start the api + worker containers too (infra is already running)
  make test        # unit + contract tests (no external services)
  make integration # tests against Postgres/Neo4j/Temporal/MinIO

  claude           # Claude Code CLI (run `claude login`, or set ANTHROPIC_API_KEY)
  codex            # OpenAI Codex CLI (run `codex login`, or set OPENAI_API_KEY)
MSG
