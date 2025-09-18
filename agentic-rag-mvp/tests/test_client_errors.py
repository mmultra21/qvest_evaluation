import io
import sys
import json
import importlib.util
from pathlib import Path

import pytest
from urllib.error import HTTPError, URLError


def _load_client_module():
    repo_root = Path(__file__).resolve().parents[2]
    client_path = repo_root / "agentic-rag-mvp" / "scripts" / "clients" / "complete.py"
    spec = importlib.util.spec_from_file_location("complete_client", str(client_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_http_error_shows_body_and_exits(capfd, monkeypatch):
    mod = _load_client_module()

    # Build an HTTPError that contains a JSON body
    body = b'{"error":"bad request"}'
    fp = io.BytesIO(body)
    he = HTTPError(url="http://x", code=400, msg="Bad Request", hdrs=None, fp=fp)

    def fake_urlopen(req, timeout=None):
        raise he

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    testargs = ["prog", "--url", "http://127.0.0.1:1234/completion", "--prompt", "x"]
    monkeypatch.setattr(sys, "argv", testargs)

    with pytest.raises(SystemExit) as se:
        mod.main()

    # main should exit with code 3 for HTTPError
    assert se.value.code == 3
    captured = capfd.readouterr()
    assert "HTTP error 400" in captured.err
    assert "bad request" in captured.err


def test_retries_on_urlerror_then_success(monkeypatch):
    mod = _load_client_module()

    responses = []

    class FakeResp:
        def __enter__(self):
            return io.BytesIO(json.dumps({"content": "ok"}).encode("utf-8"))
        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout=None):
        # First call: raise URLError; second: return valid
        if not responses:
            responses.append("tried")
            raise URLError("temporary failure")
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    testargs = ["prog", "--url", "http://127.0.0.1:1234/completion", "--prompt", "x", "--retries", "2"]
    monkeypatch.setattr(sys, "argv", testargs)

    # main should run and return normally (no SystemExit)
    mod.main()


def test_timeout_and_exit_on_network_error(monkeypatch):
    mod = _load_client_module()

    def fake_urlopen(req, timeout=None):
        raise URLError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    testargs = ["prog", "--url", "http://127.0.0.1:1234/completion", "--prompt", "x", "--retries", "1"]
    monkeypatch.setattr(sys, "argv", testargs)

    with pytest.raises(SystemExit) as se:
        mod.main()

    # main uses exit code 2 for network errors
    assert se.value.code == 2
