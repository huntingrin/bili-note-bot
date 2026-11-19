#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

fail=0
say() { printf '%s\n' "$*"; }
need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    say "missing: $1"
    fail=1
  fi
}

say "== verify doctor =="
need node
need git

if [ -f pnpm-lock.yaml ]; then
  PM=pnpm
elif [ -f yarn.lock ]; then
  PM=yarn
elif [ -f bun.lockb ] || [ -f bun.lock ]; then
  PM=bun
else
  PM=npm
fi
say "package manager: $PM"
need "$PM"

[ -f package.json ] || { say "missing: package.json"; fail=1; }
[ -f harness/verify/flows/app.boot.ts ] || { say "missing: harness/verify/flows/app.boot.ts"; fail=1; }
[ -f .env.example ] || { say "missing: .env.example"; fail=1; }
[ -x node_modules/.bin/tsx ] || { say "missing: tsx (run install)"; fail=1; }
[ -d node_modules/playwright ] || { say "missing: playwright (run install)"; fail=1; }

if [ -f package.json ] && ! grep -q '"verify"' package.json; then
  say "missing: package.json script 'verify'"
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  say "doctor: FAIL"
  exit 1
fi

say "doctor: OK"
