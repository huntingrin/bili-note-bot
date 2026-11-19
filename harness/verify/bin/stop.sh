#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

if [ -f .verify-dev.pid ]; then
  kill "$(cat .verify-dev.pid)" 2>/dev/null || true
  rm -f .verify-dev.pid
fi
