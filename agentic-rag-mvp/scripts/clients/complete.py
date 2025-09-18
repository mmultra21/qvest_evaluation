#!/usr/bin/env python3
"""Minimal, hardened client for llama-server /completion endpoint.

Features:
- Build URL from --host/--port/--endpoint or accept --url
- Timeout and simple retry on network errors
- Pretty output by default (prints the `content` field when present)
- Stdlib-only (urllib)

Usage: python scripts/clients/complete.py --prompt "Hello"
"""
import argparse
import json
import sys
import time
from urllib import request, error


def call_completion(url: str, payload: dict, timeout: float = 10.0):
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=timeout) as resp:
        # resp may be bytes; json.load handles the file-like object
        return json.load(resp)


def build_url(args) -> str:
    if args.url:
        return args.url
    endpoint = args.endpoint
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return f"http://{args.host}:{args.port}{endpoint}"


def print_result(out: object, raw: bool = False, verbose: bool = False):
    # If user asked for raw JSON, just dump
    if raw:
        print(json.dumps(out, indent=2))
        return

    # If the response is a dict with a 'content' key, print that for quick reads
    if isinstance(out, dict) and "content" in out:
        content = out.get("content")
        # content may be a string or list; handle common shapes
        if isinstance(content, list):
            for item in content:
                print(item)
        else:
            print(content)

        if verbose:
            # Print a small metadata summary
            meta = {k: v for k, v in out.items() if k != "content"}
            if meta:
                print("\n--- metadata ---")
                print(json.dumps(meta, indent=2))
        return

    # Fallback: pretty-print whatever we got
    print(json.dumps(out, indent=2))


def main():
    p = argparse.ArgumentParser()
    url_group = p.add_mutually_exclusive_group()
    url_group.add_argument("--url", help="Full URL to /completion (overrides host/port/endpoint)")
    url_group.add_argument("--host", default=None, help="Host to connect to (used with --port and --endpoint)")

    p.add_argument("--port", type=int, default=11434, help="Port for the server")
    p.add_argument("--endpoint", default="/completion", help="Endpoint path (default: /completion)")
    p.add_argument("--prompt", default="Hello Hermes3!", help="Prompt to send to the model")
    p.add_argument("--n_predict", type=int, default=64)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds")
    p.add_argument("--retries", type=int, default=1, help="Number of attempts on network error")
    p.add_argument("--raw", action="store_true", help="Print raw JSON response")
    p.add_argument("--verbose", action="store_true", help="Print extra metadata")
    args = p.parse_args()

    # If host wasn't provided and url wasn't provided, default to localhost
    if not args.url and not args.host:
        args.host = "127.0.0.1"

    target_url = build_url(args)

    payload = {"prompt": args.prompt, "n_predict": args.n_predict, "temperature": args.temperature}

    last_err = None
    for attempt in range(1, max(1, args.retries) + 1):
        try:
            out = call_completion(target_url, payload, timeout=args.timeout)
            print_result(out, raw=args.raw, verbose=args.verbose)
            return
        except error.HTTPError as he:
            # Server returned a non-2xx response
            try:
                body = he.read().decode("utf-8", errors="ignore")
            except Exception:
                body = "<no body>"
            print(f"HTTP error {he.code}: {he.reason}\n{body}", file=sys.stderr)
            sys.exit(3)
        except error.URLError as ue:
            last_err = ue
            if attempt < args.retries:
                time.sleep(0.5 * attempt)
                continue
            print("Network error:", ue, file=sys.stderr)
            sys.exit(2)
        except json.JSONDecodeError as je:
            print("Failed to decode JSON response:", je, file=sys.stderr)
            sys.exit(4)
        except Exception as e:
            print("Request failed:", e, file=sys.stderr)
            sys.exit(5)


if __name__ == "__main__":
    main()
