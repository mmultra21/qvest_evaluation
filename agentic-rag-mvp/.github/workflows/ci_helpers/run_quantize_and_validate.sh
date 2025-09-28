#!/usr/bin/env bash
set -euo pipefail

# Lightweight CI helper to run the benchmark and write JSON output
MODEL=${MODEL:-gpt2}
MODE=${MODE:-fp16}
ITER=${ITER:-5}
OUT_JSON=benchmarks/benchmark_result_ci.json

python - <<'PY'
import json, subprocess, sys
from pathlib import Path
cmd = ['python','benchmarks/benchmark_harness.py','--model', '${MODEL}','--mode','${MODE}','--iterations', '${ITER}']
print('Running:', ' '.join(cmd))
proc = subprocess.run(cmd, capture_output=True, text=True)
print(proc.stdout)
if proc.returncode != 0:
    print(proc.stderr, file=sys.stderr)
    sys.exit(proc.returncode)
# For demo, write a tiny JSON with the stdout trimmed
Path('benchmarks').mkdir(parents=True, exist_ok=True)
Path('${OUT_JSON}').write_text(json.dumps({'stdout': proc.stdout[-2000:]}, indent=2))
PY

echo "Wrote ${OUT_JSON}"
