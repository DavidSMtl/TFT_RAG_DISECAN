"""
retriever.py — Búsqueda Híbrida (Semántica + Léxica) y Reranking.

Implementa:
1. Filtrado SQL de metadatos (pre-filtering)
2. Semantic Search (ChromaDB) -> embeddings densos
3. Lexical Search (BM25) -> coincidencia exacta de términos clave
4. Reciprocal Rank Fusion (RRF) -> combinación de scores sin calibrar
5. Cross-Encoder Reranking -> precisión fina final
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import TypedDict

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from backend.chroma_store import get_all_chunks, semantic_search
from backend.db import get_ids_documentos_por_filtros
from backend.embedder import embed_query

# ── Configuración ──────────────────────────────────────────────────────────────

RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
RRF_K = 60  # Constante estándar de RRF


class SearchResult(TypedDict):
    id: str
    texto: str
    metadatos: dict
    score: float


# ── Cachés en memoria ──────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _load_reranker() -> CrossEncoder:
    print(f"[Retriever] Cargando reranker '{RERANKER_MODEL}'...")
    return CrossEncoder(RERANKER_MODEL)


@lru_cache(maxsize=1)
def _build_bm25_index() -> tuple[BM25Okapi, list[dict]]:
    """
    Carga todos los chunks de ChromaDB y construye el índice BM25 en memoria.
    Se ejecuta de forma lazy (la primera vez que se hace una búsqueda BM25).
    """
    print("[Retriever] Construyendo índice BM25 en memoria...")
    chunks = get_all_chunks()
    
    # Tokenización simple por espacios para BM25 (se podría mejorar con NLP)
    tokenized_corpus = [c["document"].lower().split() for c in chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    
    print(f"[Retriever] BM25 construido para {len(chunks)} chunks.")
    return bm25, chunks


# ── Algoritmos principales ─────────────────────────────────────────────────────


def _reciprocal_rank_fusion(
    semantic_results: list[dict],
    lexical_results: list[dict],
    top_k: int = 20,
) -> list[dict]:
    """Combina dos listas de resultados usando Reciprocal Rank Fusion."""
    
    rrf_scores: dict[str, float] = {}
    chunk_map: dict[str, dict] = {}

    # Rank 1: Semantic
    for rank, item in enumerate(semantic_results):
        cid = item["id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0) + 1.0 / (RRF_K + rank + 1)
        chunk_map[cid] = item

    # Rank 2: Lexical
    for rank, item in enumerate(lexical_results):
        cid = item["id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0) + 1.0 / (RRF_K + rank + 1)
        if cid not in chunk_map:
            chunk_map[cid] = item

    # Ordenar por score RRF descendente
    sorted_ids = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)
    
    # Devolver el top_k combinado
    combined: list[dict] = []
    for cid in sorted_ids[:top_k]:
        c = chunk_map[cid]
        c["rrf_score"] = rrf_scores[cid]
        combined.append(c)
        
    return combined


# ── API Pública ────────────────────────────────────────────────────────────────


def search_hybird(
    query: str,
    filtros: dict | None = None,
    top_k: int = 5,
    top_k_retrieval: int = 40,
) -> list[SearchResult]:
    """
    Ejecuta el pipeline completo de recuperación híbrida + reranking.
    """
    # 0. Filtros SQL
    valid_ids: list[int] | None = None
    if filtros:
        valid_ids = get_ids_documentos_por_filtros(filtros)
        if valid_ids is not None and not valid_ids:
            return []  # Si hay filtros pero no devuelven documentos, no hay nada que buscar.

    chroma_where = None
    if valid_ids is not None:
        if len(valid_ids) == 1:
            chroma_where = {"id_documento": valid_ids[0]}
        else:
            chroma_where = {"id_documento": {"$in": valid_ids}}

    # 1. Búsqueda semántica (ChromaDB)
    q_emb = embed_query(query)
    semantic_res = semantic_search(q_emb, top_k=top_k_retrieval, where=chroma_where)

    # 2. Búsqueda léxica (BM25)
    # Por eficiencia, BM25 lo hacemos en memoria sobre todos los chunks y luego filtramos
    bm25, corpus_chunks = _build_bm25_index()
    q_tokens = query.lower().split()
    bm25_scores = bm25.get_scores(q_tokens)
    
    # Juntar score con el chunk y ordenar
    lexical_all = [
        {"id": c["id"], "document": c["document"], "metadata": c["metadata"], "bm25_score": score}
        for c, score in zip(corpus_chunks, bm25_scores) if score > 0
    ]
    lexical_all.sort(key=lambda x: x["bm25_score"], reverse=True)
    
    # Aplicar el filtro SQL a posteriori en BM25
    if valid_ids is not None:
        lexical_all = [c for c in lexical_all if c["metadata"].get("id_documento") in valid_ids]
    
    lexical_res = lexical_all[:top_k_retrieval]

    # 3. Fusión Híbrida (RRF)
    combined_res = _reciprocal_rank_fusion(semantic_res, lexical_res, top_k=min(20, top_k_retrieval))
    if not combined_res:
        return []

    # 4. Cross-Encoder Reranking
    reranker = _load_reranker()
    
    cross_input = [[query, c["document"]] for c in combined_res]
    cross_scores = reranker.predict(cross_input)
    
    for score, item in zip(cross_scores, combined_res):
        item["cross_score"] = float(score)

    combined_res.sort(key=lambda x: x["cross_score"], reverse=True)

    # 5. Mapear al output top_k
    final_results: list[SearchResult] = []
    for item in combined_res[:top_k]:
        final_results.append(
            SearchResult(
                id=item["id"],
                texto=item["document"],
                metadatos=item["metadata"],
                score=item.get("cross_score", 0.0),
            )
        )

    return final_results
