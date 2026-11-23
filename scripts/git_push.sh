#!/usr/bin/env bash
set -euo pipefail

financials="${HOME}/projects/financials"
data="${HOME}/projects/data"
message="$(date '+%Y-%m-%d') automated collection"

push_repo() {
  local repo="$1"
  git -C "${repo}" add -A
  if ! git -C "${repo}" diff --cached --quiet; then
    git -C "${repo}" commit -m "${message}"
    git -C "${repo}" push origin main
  fi
}

push_repo "${financials}"
push_repo "${data}"
