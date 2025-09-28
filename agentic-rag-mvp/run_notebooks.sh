#!/usr/bin/env bash
set -euo pipefail

# run_notebooks.sh - helper entrypoint for Docker image
# If RUN_NOTEBOOKS is set to "true", execute all notebooks in ./docs using papermill
# Outputs are written to ./notebook_outputs inside the container (mounted to host via compose)

RUN_NOTEBOOKS=${RUN_NOTEBOOKS:-false}
NOTEBOOK_DIR=${NOTEBOOK_DIR:-/work/docs}
OUTPUT_DIR=${OUTPUT_DIR:-/work/notebook_outputs}

mkdir -p "$OUTPUT_DIR"

if [ "$RUN_NOTEBOOKS" = "true" ]; then
  echo "Running notebooks from $NOTEBOOK_DIR -> $OUTPUT_DIR"
  # find notebooks and execute them one-by-one with papermill
  find "$NOTEBOOK_DIR" -maxdepth 2 -type f -name "*.ipynb" | while read -r nb; do
    base=$(basename "$nb" .ipynb)
    out="$OUTPUT_DIR/${base}-executed-$(date +%Y%m%d-%H%M%S).ipynb"
    echo "Executing $nb -> $out"
    papermill "$nb" "$out" --progress-bar || echo "Papermill failed for $nb (continuing)"
  done
else
  echo "RUN_NOTEBOOKS not set to true; skipping notebook execution"
fi

# Finally exec the container CMD (Jupyter Lab in the Dockerfile)
exec "$@"
