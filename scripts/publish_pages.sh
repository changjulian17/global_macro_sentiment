#!/usr/bin/env bash
set -euo pipefail

# Build latest report and stage it for GitHub Pages deployment.
# Usage:
#   scripts/publish_pages.sh
#   RUN_ARGS="--no-browser" scripts/publish_pages.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/docs"
RUN_ARGS="${RUN_ARGS:---skip-fintwit --no-browser}"

cd "$ROOT_DIR"

if [[ -f ".venv/bin/activate" ]]; then
  # Local runs use the project's virtual environment when available.
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python run.py ${RUN_ARGS}

mkdir -p "$OUT_DIR"
cp reports/latest.html "$OUT_DIR/index.html"

cat > "$OUT_DIR/.nojekyll" <<'EOF'
EOF

cat > "$OUT_DIR/build-info.txt" <<EOF
built_at_utc=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
run_args=${RUN_ARGS}
EOF

echo "Pages artifact ready at: $OUT_DIR/index.html"
