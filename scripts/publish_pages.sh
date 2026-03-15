#!/usr/bin/env bash
set -euo pipefail

# Build latest report and stage it for GitHub Pages deployment.
# Usage:
#   scripts/publish_pages.sh
#   TRY_FINTWIT=true scripts/publish_pages.sh
#   RUN_ARGS="--skip-fintwit --no-browser" scripts/publish_pages.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/docs"
TRY_FINTWIT="${TRY_FINTWIT:-true}"
USED_RUN_ARGS=""
BUILD_MODE=""

cd "$ROOT_DIR"

if [[ -f ".venv/bin/activate" ]]; then
  # Local runs use the project's virtual environment when available.
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [[ -n "${RUN_ARGS:-}" ]]; then
  python run.py ${RUN_ARGS}
  USED_RUN_ARGS="${RUN_ARGS}"
  BUILD_MODE="explicit-run-args"
else
  if [[ "$TRY_FINTWIT" == "true" ]]; then
    echo "Attempting build with FinTwit enabled..."
    if python run.py --no-browser; then
      USED_RUN_ARGS="--no-browser"
      BUILD_MODE="fintwit-enabled"
    else
      echo "FinTwit build failed; retrying with --skip-fintwit fallback..."
      python run.py --skip-fintwit --no-browser
      USED_RUN_ARGS="--skip-fintwit --no-browser"
      BUILD_MODE="fintwit-fallback-skip"
    fi
  else
    python run.py --skip-fintwit --no-browser
    USED_RUN_ARGS="--skip-fintwit --no-browser"
    BUILD_MODE="skip-fintwit"
  fi
fi

mkdir -p "$OUT_DIR"
cp reports/latest.html "$OUT_DIR/index.html"

cat > "$OUT_DIR/.nojekyll" <<'EOF'
EOF

cat > "$OUT_DIR/build-info.txt" <<EOF
built_at_utc=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
run_args=${USED_RUN_ARGS}
build_mode=${BUILD_MODE}
EOF

echo "Pages artifact ready at: $OUT_DIR/index.html"
