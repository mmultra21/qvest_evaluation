#!/usr/bin/env python3
"""Minimal client for llama-server /completion endpoint.

Usage: python scripts/clients/complete.py --prompt "Hello"
"""
import argparse
import json
import sys
from urllib import request


def call_completion(url: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with request.urlopen(req) as resp:
        return json.load(resp)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:11434/completion")
    p.add_argument("--prompt", default="Hello Hermes3!")
    p.add_argument("--n_predict", type=int, default=64)
    p.add_argument("--temperature", type=float, default=0.2)
    args = p.parse_args()

    payload = {"prompt": args.prompt, "n_predict": args.n_predict, "temperature": args.temperature}

    try:
        out = call_completion(args.url, payload)
    except Exception as e:
        print("Request failed:", e, file=sys.stderr)
        sys.exit(2)

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
