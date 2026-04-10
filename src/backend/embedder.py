"""
embedder.py — Generación de embeddings con sentence-transformers.

Modelo: intfloat/multilingual-e5-base
  - 768 dimensiones
  - Multilingüe (excelente en español)
  - Requiere prefijo "query: " para queries y "passage: " para documentos
"""
from __future__ import annotations

import os
from functools import lru_cache

from sentence_transformers import SentenceTransformer

# ── Configuración ──────────────────────────────────────────────────────────────

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-base")
BATCH_SIZE = 64  # Ajustar según VRAM/RAM disponible


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    """Carga el modelo una sola vez (singleton en memoria)."""
    print(f"[Embedder] Cargando modelo '{MODEL_NAME}'...")
    model = SentenceTransformer(MODEL_NAME)
    print("[Embedder] Modelo cargado.")
    return model


# ── API pública ────────────────────────────────────────────────────────────────


def embed_passages(texts: list[str]) -> list[list[float]]:
    """
    Genera embeddings para una lista de pasajes (chunks del corpus).
    Añade el prefijo 'passage: ' requerido por el modelo e5.

    Args:
        texts: lista de textos a embedir

    Returns:
        lista de vectores float (768 dims cada uno)
    """
    model = _load_model()
    prefixed = [f"passage: {t}" for t in texts]
    vectors = model.encode(
        prefixed,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    return vectors.tolist()


def embed_query(query: str) -> list[float]:
    """
    Genera el embedding de una query de usuario.
    Añade el prefijo 'query: ' requerido por el modelo e5.

    Args:
        query: pregunta del usuario

    Returns:
        vector float (768 dims)
    """
    model = _load_model()
    vector = model.encode(
        f"query: {query}",
        normalize_embeddings=True,
    )
    return vector.tolist()
