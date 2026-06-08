#!/usr/bin/env bash
set -euo pipefail

# Python-dependencies voor de scraper.
pip install --no-cache-dir -r requirements.txt

# Claude Code CLI (Anthropic) en Codex CLI (OpenAI).
npm install -g @anthropic-ai/claude-code @openai/codex

echo "Geinstalleerd:"
python --version
node --version
claude --version || true
codex --version || true
