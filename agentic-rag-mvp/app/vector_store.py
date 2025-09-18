# app/vector_store.py
import os
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", None)
COLL = os.getenv("QDRANT_COLLECTION", "reading_campaign_docs")

# Choose your model
EMB_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
# examples:
# "BAAI/bge-small-en-v1.5" or "BAAI/bge-m3"

_model = None
_client = None

def _emb_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMB_NAME)
    return _model

def _client_qdrant():
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _client

def ensure_collection():
    client = _client_qdrant()
    dim = _emb_model().get_sentence_embedding_dimension()
    existing = [c.name for c in client.get_collections().collections]
    if COLL not in existing:
        client.recreate_collection(
            collection_name=COLL,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )

def embed_texts(texts: List[str]) -> List[List[float]]:
    model = _emb_model()
    return model.encode(texts, normalize_embeddings=True).tolist()

def upsert_chunks(chunks: List[Dict[str, Any]]):
    """chunks: [{id, text, meta}]"""
    ensure_collection()
    vecs = embed_texts([c["text"] for c in chunks])
    points = [
        PointStruct(id=c["id"], vector=v, payload={"text": c["text"], **(c.get("meta") or {})})
        for c, v in zip(chunks, vecs)
    ]
    _client_qdrant().upsert(collection_name=COLL, points=points)

def search(query: str, top_k: int = 5):
    ensure_collection()
    qv = embed_texts([query])[0]
    res = _client_qdrant().search(collection_name=COLL, query_vector=qv, limit=top_k)
    return res  # list[ScoredPoint]