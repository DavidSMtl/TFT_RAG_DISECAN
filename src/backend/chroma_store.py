"""
chroma_store.py: Wrapper de ChromaDB para el Vector Store

Gestiona la colección de chunks con sus embeddings y metadatos.
ChromaDB se persiste en disco (CHROMA_PATH del .env).
"""
from __future__ import annotations

import os
from functools import lru_cache

import chromadb
from chromadb import Collection

# ── Configuración ──────────────────────────────────────────────────────────────

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
COLLECTION_NAME = "disecan_chunks"
EMBEDDING_DIM = 768  # multilingual-e5-base


@lru_cache(maxsize=1)
def _get_client() -> chromadb.PersistentClient:
    """Cliente ChromaDB singleton (persistente en disco)."""
    return chromadb.PersistentClient(path=CHROMA_PATH)


def get_collection() -> Collection:
    """
    Devuelve (o crea) la colección principal de chunks.
    Usa embeddings pre-computados (embedding_function=None).
    """
    client = _get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},  # Similitud coseno
    )


# ── Operaciones de escritura ───────────────────────────────────────────────────


def upsert_chunks(
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict],
) -> None:
    """
    Inserta o actualiza chunks en la colección.
    Usa upsert para que se pueda ejecutar sin duplicados.

    Args:
        ids        : identificadores únicos (UUID string)
        embeddings : vectores pre-computados (lista de listas)
        documents  : textos de los chunks (para búsqueda BM25 y display)
        metadatas  : dicts con orador, legislatura, fecha, numSesion, idDocumento, etc.
    """
    col = get_collection()
    col.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )


# ── Operaciones de lectura ─────────────────────────────────────────────────────


def semantic_search(
    query_embedding: list[float],
    top_k: int = 50,
    where: dict | None = None,
) -> list[dict]:
    """
    Búsqueda semántica por similitud coseno.

    Args:
        query_embedding : embedding de la query (768 dims)
        top_k           : número máximo de resultados
        where           : filtro de metadatos ChromaDB (ej: {"legislatura": "X"})

    Returns:
        lista de dicts con keys: id, document, metadata, distance
    """
    col = get_collection()
    kwargs: dict = {
        "query_embeddings": [query_embedding],
        "n_results": min(top_k, col.count() or 1),
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    results = col.query(**kwargs)

    # Aplanar estructura de resultados (ChromaDB devuelve listas anidadas)
    output: list[dict] = []
    for i, chunk_id in enumerate(results["ids"][0]):
        output.append(
            {
                "id": chunk_id,
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            }
        )
    return output


def get_all_chunks(where: dict | None = None) -> list[dict]:
    """
    Recupera todos los chunks (para construir índice BM25 en memoria).
    Atención: con 1.5M frases agrupadas en decenas de miles de chunks,
    puede ocupar bastante RAM. Se llama una sola vez al inicio.

    Returns:
        lista de dicts con keys: id, document, metadata
    """
    col = get_collection()
    total = col.count()
    if total == 0:
        return []

    results = col.get(
        where=where,
        include=["documents", "metadatas"],
        limit=total,
    )

    output: list[dict] = []
    for i, chunk_id in enumerate(results["ids"]):
        output.append(
            {
                "id": chunk_id,
                "document": results["documents"][i],
                "metadata": results["metadatas"][i],
            }
        )
    return output


def count_chunks() -> int:
    """Número total de chunks indexados."""
    return get_collection().count()
