import json

from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_campaign_current():
    r = client.get("/campaign/current")
    assert r.status_code == 200
    j = r.json()
    assert "title" in j
    assert "seed_list" in j


def test_recommend_and_justify_flow():
    payload = {"grade": 4, "interests": ["sports"], "progress_bucket": "starter", "top_k": 3}
    r = client.post("/recommend", json=payload)
    assert r.status_code == 200
    rec = r.json()
    assert "candidates" in rec
    assert isinstance(rec["candidates"], list)
    if not rec["candidates"]:
        # If no candidates returned, that's unexpected but don't crash the test runner
        assert False, "recommend returned empty candidates"

    # Pick first candidate and call justify
    cands = rec["candidates"]
    jr = client.post(
        "/justify",
        json={"candidates": cands, "student": {"grade": 4, "interests": ["sports"], "progress_bucket": "starter"}, "notes": None},
    )
    assert jr.status_code == 200
    jresp = jr.json()
    assert "items" in jresp
    assert isinstance(jresp["items"], list)
    if jresp["items"]:
        itm = jresp["items"][0]
        assert "catalog_id" in itm
        assert "pitch" in itm
        assert "why" in itm


def test_justify_returns_422_on_malformed_llm(monkeypatch):
    """Simulate LLM drift: rag.justify returns items missing a Lexile clause and /justify should return 422."""

    # Prepare a malformed item (why lacks 'Lexile')
    bad_items = [
        {"catalog_id": "bk1", "pitch": "A short pitch.", "why": "too short note", "shelf": "featured"}
    ]

    def fake_justify(_req):
        return bad_items

    # Patch the rag.justify function used by the API
    import api.tools.rag as rag_mod

    monkeypatch.setattr(rag_mod, "justify", fake_justify)

    # Now call the endpoint with a valid candidate payload
    payload = {"candidates": [{"catalog_id": "bk1", "payload": {}, "scores": {}, "reason_tags": []}], "student": {"grade": 4, "interests": ["sports"], "progress_bucket": "starter"}, "notes": None}
    r = client.post("/justify", json=payload)
    assert r.status_code == 422
