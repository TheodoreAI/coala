#!/usr/bin/env bash
# init_global_repo.sh — one-time setup for the global context ledger's
# own git repo. Safe to re-run: skips steps that are already done.
#
# Usage:
#   ./init_global_repo.sh                     # uses ~/.claude/global-decisions
#   DECISION_LEDGER_GLOBAL=/custom/path/decisions ./init_global_repo.sh
#
# After running this on laptop #1, create an empty remote repo (GitHub,
# GitLab, a private git server, etc.) and run the "git remote add" +
# "git push" lines it prints at the end. Then on laptop #2, just:
#   git clone <remote-url> ~/.claude/global-decisions

set -euo pipefail

if [ -n "${DECISION_LEDGER_GLOBAL:-}" ]; then
  ROOT="$(dirname "$DECISION_LEDGER_GLOBAL")"
else
  ROOT="$HOME/.claude/global-decisions"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GITATTRS_SRC="$SCRIPT_DIR/../assets/gitattributes-template"

echo "Setting up global context ledger at: $ROOT"
mkdir -p "$ROOT/decisions"
cd "$ROOT"

if [ -d ".git" ]; then
  echo "Already a git repo — skipping git init."
else
  git init -q
  echo "Initialized git repo."
fi

if [ -f ".gitattributes" ]; then
  echo ".gitattributes already present — leaving it alone."
elif [ -f "$GITATTRS_SRC" ]; then
  cp "$GITATTRS_SRC" .gitattributes
  echo "Copied .gitattributes (pins LF line endings across OSes)."
else
  # Fallback if the script is run outside the packaged skill folder.
  cat > .gitattributes << 'EOF'
* text=auto eol=lf
*.yaml text eol=lf
EOF
  echo "Wrote a default .gitattributes (pins LF line endings across OSes)."
fi

# git commit needs an identity configured somewhere (this repo, or
# globally). Check before attempting the commit so a first-time git user
# gets a clear instruction instead of a raw git error mid-script.
if ! git config user.email > /dev/null 2>&1 || ! git config user.name > /dev/null 2>&1; then
  echo ""
  echo "Git doesn't have your identity configured yet (needed before it will let you commit)."
  echo "Run this once, then re-run this script:"
  echo "  git config --global user.email \"you@example.com\""
  echo "  git config --global user.name \"Your Name\""
  exit 1
fi

# Make sure git has *something* to commit even before any decisions exist.
touch decisions/.gitkeep

git add -A
if git diff --cached --quiet; then
  echo "Nothing new to commit."
else
  git commit -q -m "init global context ledger"
  echo "Committed."
fi

echo ""
echo "Local repo ready at $ROOT"
echo ""
echo "Next steps:"
echo "  1. Create an empty remote repo (private, e.g. on GitHub)."
echo "  2. Run:"
echo "       cd \"$ROOT\""
echo "       git remote add origin <remote-url>"
echo "       git branch -M main"
echo "       git push -u origin main"
echo "  3. On your other laptop:"
echo "       git clone <remote-url> ~/.claude/global-decisions"
