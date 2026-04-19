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

import torch
from sentence_transformers import SentenceTransformer

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-base")
BATCH_SIZE = 64


@lru_cache(maxsize=1)
def _load_model(device: str | None = None) -> SentenceTransformer:
    """Carga el modelo una sola vez (singleton en memoria)."""
    # Forzamos CPU por defecto en entornos locales para liberar VRAM para Ollama
    if device is None:
        device = "cpu"
    
    print(f"[Embedder] Cargando modelo '{MODEL_NAME}' en dispositivo '{device}'...")
    try:
        model = SentenceTransformer(MODEL_NAME, device=device)
        print(f"[Embedder] Modelo cargado con éxito en '{device}'.")
        return model
    except Exception as e:
        print(f"[Embedder] ERROR cargando modelo: {e}")
        # Fallback de emergencia a CPU
        if device != "cpu":
            print("[Embedder] Reintentando carga en CPU...")
            return SentenceTransformer(MODEL_NAME, device="cpu")
        raise e


def embed_passages(texts: list[str], device: str | None = None) -> list[list[float]]:
    """
    Genera embeddings para una lista de pasajes (chunks del corpus).
    Añade el prefijo 'passage: ' requerido por el modelo e5.
    """
    model = _load_model(device)
    prefixed = [f"passage: {t}" for t in texts]
    vectors = model.encode(
        prefixed,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    return vectors.tolist()


def embed_query(query: str, device: str | None = None) -> list[float]:
    """
    Genera el embedding de una query de usuario.
    Añade el prefijo 'query: ' requerido por el modelo e5.
    """
    model = _load_model(device)
    vector = model.encode(
        f"query: {query}",
        normalize_embeddings=True,
    )
    return vector.tolist()
