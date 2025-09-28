"""Benchmark harness for Hermes3 model variants.

Usage examples:

python benchmarks/benchmark_harness.py \
  --model MODEL_PATH \
  --tokenizer MODEL_PATH \
  --mode fp16 \
  --prompt-file benchmarks/sample_prompts.txt \
  --iterations 50

This script is intentionally conservative: it imports heavy libs lazily and guards operations so importing the module alone won't crash if bitsandbytes is missing.
"""

import argparse
import time
import statistics
import os
from pathlib import Path

# Lazy imports inside functions to keep module import safe

def load_prompts(path: str):
    p = Path(path)
    if not p.exists():
        return ["Hello, what's the weather today?", "Tell me a short story about a brave librarian."]
    return [l.strip() for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]


def make_model_loader(model_path: str, mode: str):
    """Return a callable that loads model+tokenizer according to the mode.

    Modes:
      - fp16: torch_dtype=torch.float16
      - int8: load_in_8bit=True (bitsandbytes)
      - gptq4: assumes model path is already GPTQ-quantized and loadable by the chosen runner
    """
    def loader():
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch

        tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=True)

        if mode == 'fp16':
            model = AutoModelForCausalLM.from_pretrained(model_path, torch_dtype=torch.float16, device_map='auto')
        elif mode == 'int8':
            # Load in 8-bit via bitsandbytes if installed
            model = AutoModelForCausalLM.from_pretrained(model_path, load_in_8bit=True, device_map='auto')
        elif mode == 'gptq4':
            # GPTQ models are assumed pre-quantized and loadable; attempt a normal load
            model = AutoModelForCausalLM.from_pretrained(model_path, device_map='auto')
        else:
            raise ValueError('unknown mode: ' + mode)

        model.eval()
        return model, tokenizer

    return loader


def peak_memory_usage_mb():
    # Try to get process memory info (RSS) via psutil, fallback to 0
    try:
        import psutil
        proc = psutil.Process()
        return proc.memory_info().rss / (1024 ** 2)
    except Exception:
        return 0.0


def run_single_inference(model, tokenizer, prompt: str, max_new_tokens=64):
    import torch

    inputs = tokenizer(prompt, return_tensors='pt')
    # Move inputs to model device if necessary
    device = next(model.parameters()).device
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens)
    return tokenizer.decode(out[0], skip_special_tokens=True)


def benchmark(model_loader, prompts, iterations: int, warmup: int = 5):
    # Load model
    t0 = time.time()
    model, tokenizer = model_loader()
    load_time = time.time() - t0

    # Warmup
    for i in range(min(warmup, iterations)):
        run_single_inference(model, tokenizer, prompts[i % len(prompts)])

    mem_before = peak_memory_usage_mb()
    times = []
    for i in range(iterations):
        prompt = prompts[i % len(prompts)]
        t1 = time.time()
        run_single_inference(model, tokenizer, prompt)
        t2 = time.time()
        times.append((t2 - t1) * 1000.0)  # ms

    mem_after = peak_memory_usage_mb()
    peak_mem_mb = max(mem_before, mem_after)

    stats = {
        'load_time_s': load_time,
        'iterations': iterations,
        'mean_ms': statistics.mean(times) if times else 0,
        'p50_ms': statistics.median(times) if times else 0,
        'p95_ms': sorted(times)[int(len(times) * 0.95) - 1] if times else 0,
        'p99_ms': sorted(times)[int(len(times) * 0.99) - 1] if times else 0,
        'peak_mem_mb': peak_mem_mb,
    }
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True, help='model path or HF name')
    parser.add_argument('--tokenizer', required=False, help='tokenizer path (defaults to model)')
    parser.add_argument('--mode', choices=['fp16', 'int8', 'gptq4'], default='fp16')
    parser.add_argument('--prompt-file', default='benchmarks/sample_prompts.txt')
    parser.add_argument('--iterations', type=int, default=20)
    parser.add_argument('--warmup', type=int, default=3)
    args = parser.parse_args()

    model_path = args.model
    tokenizer_path = args.tokenizer or args.model
    prompts = load_prompts(args.prompt_file)

    loader = make_model_loader(model_path, args.mode)

    print(f'Running benchmark: model={model_path} mode={args.mode} iterations={args.iterations}')
    stats = benchmark(loader, prompts, iterations=args.iterations, warmup=args.warmup)

    print('\nBenchmark results:')
    for k, v in stats.items():
        print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
