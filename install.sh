#!/usr/bin/env bash
# install.sh — copy the coala skills into an agent's skills directory.
#
# Usage:
#   ./install.sh                          # installs to ~/.claude/skills
#   ./install.sh ~/.config/opencode/skills # installs anywhere else
#   SKILLS_DIR=/custom/path ./install.sh
#
# Safe to re-run: skips a skill whose target already exists unless --force
# is given, so it never silently clobbers local edits you've made to an
# already-installed copy.

set -euo pipefail

FORCE=0
TARGET=""
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    *) TARGET="$arg" ;;
  esac
done

SKILLS_DIR="${TARGET:-${SKILLS_DIR:-$HOME/.claude/skills}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/skills"

echo "Installing coala skills into: $SKILLS_DIR"
mkdir -p "$SKILLS_DIR"

for skill in memory context-ledger episodic-memory decision-loop; do
  dest="$SKILLS_DIR/$skill"
  if [ -d "$dest" ] && [ "$FORCE" -ne 1 ]; then
    echo "  SKIP   $skill (already exists at $dest — pass --force to overwrite)"
    continue
  fi
  rm -rf "$dest"
  cp -r "$SRC/$skill" "$dest"
  echo "  OK     $skill -> $dest"
done

cat << 'EOF'

Done. Two things left, both manual on purpose (this script won't edit your
agent config for you):

1. Point your agent's instructions file at the four skills. Add to
   CLAUDE.md / AGENTS.md (or your tool's equivalent):

   ## Persistent memory
       python3 <skills-dir>/memory/scripts/memory.py <command>
   ## Decisions
       python3 <skills-dir>/context-ledger/scripts/decisions.py <command>
   ## Decision loop
       See the decision-loop skill for the propose/evaluate/select discipline.
   ## Episodic memory
       python3 <skills-dir>/episodic-memory/scripts/episodes.py <command>

   Each skill's SKILL.md has the full guidance and exact commands — the
   snippet above is just enough for your agent to know the tools exist.

2. If you want the global context ledger synced across machines, run once:
     bash skills/context-ledger/scripts/init_global_repo.sh
   and follow the printed steps to add a remote.

See README.md for the design rationale and benchmark/RESULTS.md for evidence
that the explicit decision-loop prompting (not just having the tools) is what
produces the measured benefit.
EOF
