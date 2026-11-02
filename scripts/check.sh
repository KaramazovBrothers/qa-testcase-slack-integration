#!/bin/sh
# Run every check that CI runs, locally.
#
# CI (.github/workflows/ci.yml) invokes the same steps; keeping them in one
# script means a green local run really means a green pipeline.
set -eu

cd "$(dirname "$0")/.."

echo "==> module graph"
python3 scripts/build_static.py --validate

echo "==> committed bundle is up to date"
python3 scripts/build_static.py --check

echo "==> python tests"
.venv/bin/python -m unittest discover -s tests

echo "==> frontend unit tests"
npm test

echo "==> every source module loads"
for file in $(find static-src -name '*.js' | sort); do
  spec="./${file#static-src/}"
  if [ "$spec" = "./generator/main.js" ]; then
    echo "skip (browser entry, needs document): $spec"
    continue
  fi
  (cd static-src && node --input-type=module -e "import('$spec')")
done

if [ -n "${LEGACY_GENERATOR:-}" ]; then
  echo "==> parity with the legacy generator"
  node tests/js/parity-with-legacy.mjs "$LEGACY_GENERATOR"
  node tests/js/feature-parity.mjs "$LEGACY_GENERATOR"
else
  echo "==> parity skipped (set LEGACY_GENERATOR to compare against a pre-refactor build)"
fi

echo "\nAll checks passed."
