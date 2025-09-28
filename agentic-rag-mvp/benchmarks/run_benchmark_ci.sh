#!/usr/bin/env bash
set -euo pipefail

# CI-friendly benchmark runner: assumes a model is available in $MODEL or huggingface access
MODEL=${MODEL:-"gpt2"}
MODE=${MODE:-"fp16"}
ITER=${ITER:-10}

python benchmarks/benchmark_harness.py --model "$MODEL" --mode "$MODE" --prompt-file benchmarks/sample_prompts.txt --iterations "$ITER"
