#!/usr/bin/env bash
# Fail when extension/ changed against the base branch but extension/manifest.json "version" did not.
# Usage: scripts/check-extension-version.sh [base-ref]   (default origin/main)
set -euo pipefail
base="${1:-origin/main}"
changed="$(git diff --name-only "$base"...HEAD -- extension/)"
if [ -z "$changed" ]; then
  echo "extension/ unchanged; no version bump needed."
  exit 0
fi
version_of() { sed -n 's/^ *"version": *"\([0-9.]*\)".*/\1/p' | head -1; }
old="$(git show "$base:extension/manifest.json" 2>/dev/null | version_of || true)"
new="$(version_of < extension/manifest.json)"
if [ -n "$old" ] && [ "$old" = "$new" ]; then
  echo "extension/ changed but manifest version is still $new. Bump \"version\" in extension/manifest.json."
  echo "$changed"
  exit 1
fi
echo "Extension version: ${old:-none} -> $new"
