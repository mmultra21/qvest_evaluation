import io
import json
import sys
import pytest
from pathlib import Path
import importlib.util


def _load_client_module():
    repo_root = Path(__file__).resolve().parents[2]
    client_path = repo_root / "agentic-rag-mvp" / "scripts" / "clients" / "complete.py"
    spec = importlib.util.spec_from_file_location("complete_client", str(client_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_url_defaults_and_override():
    mod = _load_client_module()
    class Args:
        url = None
        host = None
        port = 11434
        endpoint = "/completion"

    args = Args()
    # no host/url provided -> caller should default host to 127.0.0.1 before building
    args.host = "127.0.0.1"
    assert mod.build_url(args) == "http://127.0.0.1:11434/completion"

    # explicit url should win
    args.url = "http://example.local:8000/complete"
    assert mod.build_url(args) == "http://example.local:8000/complete"


def test_print_result_content_and_raw(capfd):
    mod = _load_client_module()
    out = {"content": "abc", "meta": 1}
    mod.print_result(out, raw=False, verbose=False)
    captured = capfd.readouterr()
    assert "abc" in captured.out

    # raw
    mod.print_result(out, raw=True, verbose=False)
    captured = capfd.readouterr()
    # should be valid json
    parsed = json.loads(captured.out)
    assert parsed["content"] == "abc"


def test_print_result_verbose(capfd):
    mod = _load_client_module()
    out = {"content": "hi", "tokens": 5}
    mod.print_result(out, raw=False, verbose=True)
    captured = capfd.readouterr()
    assert "hi" in captured.out
    assert "metadata" in captured.out


def test_call_completion_invalid_json(monkeypatch):
    mod = _load_client_module()

    class FakeResp:
        def __enter__(self):
            return io.BytesIO(b"not-json")
        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout=None):
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(Exception):
        mod.call_completion("http://127.0.0.1:11434/completion", {"prompt": "x"})
