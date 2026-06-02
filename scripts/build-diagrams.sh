#!/usr/bin/env bash
# Render the diagram sources → matching .svg.
#   *.d2  → box/graph diagrams via d2 (https://d2lang.com — `brew install d2`)
# The source files (.d2) are the truth; the .svg files are generated.
set -euo pipefail

cd "$(dirname "$0")/.."
shopt -s nullglob

if ! command -v d2 >/dev/null 2>&1; then
  echo "d2 not installed — run: brew install d2" >&2
  exit 1
fi

for src in docs/diagrams/*.d2; do
  out="${src%.d2}.svg"
  echo "rendering $src → $out"
  d2 --theme 0 --dark-theme 200 --pad 20 "$src" "$out"
done

echo "done."
