#!/usr/bin/env bash
set -euo pipefail

financials="${HOME}/projects/financials"
data="${HOME}/projects/data"

pull_repo() {
  local repo="$1"
  if [[ -d "${repo}/.git" ]]; then
    git -C "${repo}" pull --ff-only origin main
  else
    echo "Not a git checkout: ${repo}" >&2
    return 1
  fi
}

pull_repo "${financials}"
pull_repo "${data}"
