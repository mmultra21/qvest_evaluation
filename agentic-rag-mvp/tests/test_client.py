import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytest
import importlib.util
import sys
from pathlib import Path


FAKE_RESPONSE = {"content": "hello from fake server", "model": "gpt-3.5-turbo"}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        _ = self.rfile.read(length)
        body = json.dumps(FAKE_RESPONSE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # silence test noise
        return


@pytest.fixture
def http_server(tmp_path):
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}/completion"

    server.shutdown()
    thread.join(timeout=1)


def _load_client_module():
    # Load the client module directly from its file location
    repo_root = Path(__file__).resolve().parents[2]
    client_path = repo_root / "agentic-rag-mvp" / "scripts" / "clients" / "complete.py"
    spec = importlib.util.spec_from_file_location("complete_client", str(client_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_client_parses_completion(http_server, monkeypatch):
    client_mod = _load_client_module()
    out = client_mod.call_completion(http_server, {"prompt": "x"})
    assert isinstance(out, dict)
    assert out.get("content") == FAKE_RESPONSE["content"]
