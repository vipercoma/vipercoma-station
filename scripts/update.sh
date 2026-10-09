#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -n $(git status --porcelain) ]]; then
  echo 'Source changes present. Commit or preserve them before updating.' >&2; exit 1
fi
git pull --ff-only
sudo bash scripts/install.sh
