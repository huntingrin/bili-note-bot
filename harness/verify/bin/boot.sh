#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

BASE_URL="${BASE_URL:-http://localhost:3000}"

if [ -f pnpm-lock.yaml ]; then
  DEFAULT_PM=pnpm
elif [ -f yarn.lock ]; then
  DEFAULT_PM=yarn
elif [ -f bun.lockb ] || [ -f bun.lock ]; then
  DEFAULT_PM=bun
else
  DEFAULT_PM=npm
fi
PM="${PACKAGE_MANAGER:-$DEFAULT_PM}"

if [ -f .verify-dev.pid ] && kill -0 "$(cat .verify-dev.pid)" 2>/dev/null; then
  echo "dev server already running (pid $(cat .verify-dev.pid))"
  exit 0
fi

"$PM" run dev > .verify-dev.log 2>&1 &
echo $! > .verify-dev.pid

for _ in $(seq 1 60); do
  if curl -fsS "$BASE_URL" >/dev/null 2>&1; then
    echo "dev server ready: $BASE_URL"
    exit 0
  fi
  sleep 1
done

echo "dev server failed to start; see .verify-dev.log" >&2
exit 1
