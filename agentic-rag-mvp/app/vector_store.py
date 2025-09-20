# app/vector_store.py
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

# ---- Embeddings (SentenceTransformers) ----
# pip install sentence-transformers
from sentence_transformers import SentenceTransformer

# -----------------------------
# Environment configuration
# -----------------------------
QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333").strip()
COLLECTION = os.getenv("QDRANT_COLLECTION", "reading_campaign_docs").strip()
EMBED_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").strip()
RECREATE_COLLECTION = os.getenv("RECREATE_COLLECTION", "0").strip() in ("1", "true", "True")

# Known dims for popular models to avoid a warmup embed if we can
KNOWN_DIMS = {
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "BAAI/bge-large-en-v1.5": 1024,
    "BAAI/bge-m3": 1024,
}

# -----------------------------
# Client & model singletons
# -----------------------------
_client: Optional[QdrantClient] = None
_model: Optional[SentenceTransformer] = None
_vector_size: Optional[int] = None


def client() -> QdrantClient:
    global _client
    if _client is None:
        # Use URL; if you run Docker with port mapping, this is correct
        _client = QdrantClient(url=QDRANT_URL)
    return _client


def embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL_NAME)
    return _model


def embedding_dim() -> int:
    """Return the vector size for the current embedding model."""
    global _vector_size
    if _vector_size is not None:
        return _vector_size

    # Exact match first
    if EMBED_MODEL_NAME in KNOWN_DIMS:
        _vector_size = KNOWN_DIMS[EMBED_MODEL_NAME]
        return _vector_size

    # Fallback: probe a single embedding to infer dim
    test = embedder().encode(["hello world"], normalize_embeddings=True)
    # SentenceTransformers returns ndarray shape (1, dim)
    _vector_size = int(getattr(test, "shape", [0, 0])[1])
    if not _vector_size:
        # final fallback
        _vector_size = len(test[0])
    return _vector_size


# -----------------------------
# Qdrant collection helpers
# -----------------------------
def ensure_collection() -> None:
    """Create (or recreate) the collection with the correct vector size."""
    c = client()
    dim = embedding_dim()

    try:
        info = c.get_collection(COLLECTION)
        current_dim = info.vectors_count  # not reliable for dim; use config below if available
        # Better: ask for collection config
        cfg = c.get_collection(COLLECTION).config
        configured = None
        try:
            # qdrant_client >= 1.7 has .vectors and .params access
            # single vector
            configured = getattr(cfg.params.vectors, "size", None)
        except Exception:
            configured = None

        if configured is not None and int(configured) == dim and not RECREATE_COLLECTION:
            return  # all good, no changes
        if not RECREATE_COLLECTION and configured is not None and int(configured) != dim:
            # Mismatch but not allowed to recreate—raise a clear error
            raise RuntimeError(
                f"Qdrant collection '{COLLECTION}' has vector size {configured}, "
                f"but embedding model '{EMBED_MODEL_NAME}' uses {dim}. "
                f"Set RECREATE_COLLECTION=1 to recreate the collection."
            )
        # else: recreate
        c.recreate_collection(
            collection_name=COLLECTION,
            vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
        )
        return
    except Exception:
        # Probably doesn't exist—create fresh
        c.recreate_collection(
            collection_name=COLLECTION,
            vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
        )


# -----------------------------
# ID normalization (UUID)
# -----------------------------
def _qdrant_id(raw_id: Any) -> str:
    """
    Qdrant 'id' must be an unsigned integer or UUID.
    - Keep if already UUID.
    - Otherwise derive a stable UUIDv5 from the string.
    """
    s = str(raw_id)
    try:
        return str(uuid.UUID(s))
    except Exception:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"qdrant:{s}"))


# -----------------------------
# Embedding & upsert
# -----------------------------
def _encode_texts(texts: List[str]) -> List[List[float]]:
    # Normalize embeddings to unit length (good for cosine)
    vecs = embedder().encode(texts, normalize_embeddings=True)
    # Ensure pure Python lists
    return [v.tolist() for v in vecs]


def upsert_chunks(chunks: Iterable[Dict[str, Any]], batch_size: int = 64) -> int:
    """
    Upsert a list of chunks into Qdrant.
    Expected chunk format:
      {"id": str|int, "text": str, "meta": {...}}
    Returns number of points sent.
    """
    ensure_collection()
    c = client()

    # Filter minimal valid chunks
    material: List[Tuple[str, str, Dict[str, Any]]] = []
    for ch in chunks:
        text = (ch.get("text") or "").strip()
        if not text:
            continue
        cid = _qdrant_id(ch.get("id"))
        payload = ch.get("meta") or {}
        # keep a copy of text in payload for retrieval/synthesis
        payload = {"text": text, **payload}
        material.append((cid, text, payload))

    if not material:
        return 0

    # Batch
    sent = 0
    for i in range(0, len(material), batch_size):
        batch = material[i : i + batch_size]
        ids = [cid for cid, _, _ in batch]
        texts = [txt for _, txt, _ in batch]
        payloads = [pl for _, _, pl in batch]
        vectors = _encode_texts(texts)

        points = [
            qmodels.PointStruct(id=ids[j], vector=vectors[j], payload=payloads[j])
            for j in range(len(batch))
        ]
        c.upsert(collection_name=COLLECTION, points=points)
        sent += len(points)

    return sent


# -----------------------------
# Search
# -----------------------------
@dataclass
class Hit:
    id: str
    score: float
    payload: Dict[str, Any]

def search(query: str, top_k: int = 5) -> List[Hit]:
    ensure_collection()
    c = client()
    vec = _encode_texts([query])[0]

    resp = c.search(
        collection_name=COLLECTION,
        query_vector=vec,
        limit=max(1, int(top_k)),
        with_payload=True,
        with_vectors=False,
        score_threshold=None,  # let the router decide
    )
    out: List[Hit] = []
    for r in resp or []:
        out.append(Hit(id=str(r.id), score=float(r.score), payload=(r.payload or {})))
    # Sort highest score first
    out.sort(key=lambda h: h.score, reverse=True)
    return out


# -----------------------------
# Stats (for Admin panel)
# -----------------------------
def stats() -> Dict[str, Any]:
    try:
        ensure_collection()
        c = client()

        # Basic info (works across client versions)
        info = c.get_collection(COLLECTION)

        # Points count (portable)
        try:
            cnt = c.count(COLLECTION, exact=True)
            points_count = int(getattr(cnt, "count", 0))
        except Exception:
            points_count = None

        # Try to read configured vector size (schema)
        configured_dim = None
        try:
            cfg = getattr(info, "config", None) or {}
            params = getattr(cfg, "params", None)
            vectors = getattr(params, "vectors", None)
            if isinstance(vectors, qmodels.VectorParams):
                configured_dim = int(vectors.size)
            elif isinstance(vectors, dict) and vectors:
                # named vectors; take the first one
                any_vec = next(iter(vectors.values()))
                configured_dim = int(getattr(any_vec, "size", 0)) or None
        except Exception:
            configured_dim = None

        return {
            "collection": COLLECTION,
            "qdrant_url": QDRANT_URL,
            "embedding_model": EMBED_MODEL_NAME,
            "embedding_dim": embedding_dim(),
            "configured_dim": configured_dim,
            "points_count": points_count,
            "status": getattr(info, "status", None),
        }
    except Exception as e:
        return {"error": str(e), "collection": COLLECTION, "qdrant_url": QDRANT_URL}