# Cairn development container: Python 3.12, uv, Node.js 22, npm, git, curl,
# PostgreSQL client, common shell tools, and the Claude Code / OpenAI Codex
# CLIs. Runs as the non-root `vscode` user.
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

ARG NODE_MAJOR=22
# The base image's Yarn apt source has a rotated signing key that breaks
# `apt-get update`; Cairn uses npm, so drop it.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg git make jq less vim-tiny htop iputils-ping netcat-openbsd \
      postgresql-client \
 && curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g @anthropic-ai/claude-code @openai/codex

COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /uvx /usr/local/bin/

# Pre-create volume mount points so they are owned by the dev user, not root.
# Persist shell history in a named volume mounted at /commandhistory.
RUN mkdir -p /home/vscode/.cache/uv && chown -R vscode:vscode /home/vscode/.cache \
 && mkdir -p /commandhistory \
 && touch /commandhistory/.bash_history /commandhistory/.zsh_history \
 && chown -R vscode:vscode /commandhistory \
 && echo 'export HISTFILE=/commandhistory/.zsh_history; setopt INC_APPEND_HISTORY' >> /home/vscode/.zshrc \
 && echo 'export HISTFILE=/commandhistory/.bash_history; export PROMPT_COMMAND="history -a"' >> /home/vscode/.bashrc

ENV UV_LINK_MODE=copy \
    PYTHONPYCACHEPREFIX=/home/vscode/.cache/pycache \
    UV_PYTHON_DOWNLOADS=never \
    GRAPHITI_TELEMETRY_ENABLED=false

USER vscode
