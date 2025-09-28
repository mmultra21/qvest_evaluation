Hermes3 benchmark harness

Purpose

This small harness measures per-request latency and peak memory usage for different model precision settings (FP16, 8-bit via bitsandbytes, and 4-bit/GPTQ where supported). It's intentionally lightweight and intended for local or CI use to compare model variants.

Files

- benchmark_harness.py - main harness. Runs a set of prompts against a model and reports latency percentiles and peak memory.
- requirements.txt - minimal dependencies for running the harness.

Quick start

1. Create a virtualenv and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r benchmarks/requirements.txt
```

2. Run the harness (example):

```bash
python benchmarks/benchmark_harness.py \
  --model MODEL_PATH \
  --tokenizer TOKENIZER_PATH \
  --mode fp16 \
  --prompt-file benchmarks/sample_prompts.txt \
  --iterations 50
```

Modes

- fp16: load model in float16 (torch_dtype=torch.float16)
- int8: load model with bitsandbytes load_in_8bit=True
- gptq4: run with an externally quantized GPTQ model (assumes model files are already quantized)

Notes

- The harness focuses on measuring latency and peak memory. For robust production benchmarking, use dedicated tooling (perf traces, GPU profilers, long-running load tests).
