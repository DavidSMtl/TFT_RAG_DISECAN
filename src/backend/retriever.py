"""
retriever.py — Búsqueda Híbrida (Ensemble) compatible con LlamaIndex.

Implementa la recuperación en paralelo:
1. Rama Semántica: Vector Store (ChromaDB)
2. Rama Léxica: BM25 sobre el corpus de la DB
"""
from __future__ import annotations

import asyncio
from typing import List

from llama_index.core import VectorStoreIndex, QueryBundle
from llama_index.core.retrievers import (
    BaseRetriever,
    VectorIndexRetriever,
    QueryFusionRetriever
)
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.schema import NodeWithScore

from llama_index.core.schema import TextNode
from backend.chroma_store import get_all_chunks

# ── Cache Global para el Retriever ──────────────────────────────────────────
_CACHED_LEXICAL_RETRIEVER = None
_CACHED_NODES = None

def get_ensemble_retriever(index: VectorStoreIndex, filtros: dict | None = None) -> BaseRetriever:
    """
    Crea un QueryFusionRetriever que combina la búsqueda semántica y léxica.
    Mantiene el índice BM25 en caché para evitar re-lecturas masivas.
    """
    global _CACHED_LEXICAL_RETRIEVER, _CACHED_NODES
    
    # 1. Rama Semántica (Consulta directa a Chroma) - Siempre fresca para soportar filtros
    vector_retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=40,
        filters=_parse_filters_to_llamaindex(filtros) if filtros else None
    )
    
    # 2. Rama Léxica (BM25) - Cacheada
    if _CACHED_LEXICAL_RETRIEVER is None:
        print("[Retriever] Construyendo índice inicial BM25 (esto puede tardar la primera vez)...")
        chunks = get_all_chunks()
        _CACHED_NODES = [
            TextNode(text=c["document"], id_=c["id"], metadata=c["metadata"]) 
            for c in chunks
        ]
        
        if _CACHED_NODES:
            _CACHED_LEXICAL_RETRIEVER = BM25Retriever.from_defaults(
                nodes=_CACHED_NODES,
                similarity_top_k=40,
            )
        else:
            print("[Retriever] ADVERTENCIA: No hay documentos para BM25.")
    
    # Si no hay BM25 (BD vacía o error), usamos la rama semántica
    if _CACHED_LEXICAL_RETRIEVER is None:
        return vector_retriever

    # 3. Fusión por RRF (Reciprocal Rank Fusion)
    print(f"[Retriever] Ejecutando búsqueda híbrida (Semántica + BM25) para top_k=10...")
    
    ensemble_retriever = QueryFusionRetriever(
        [vector_retriever, _CACHED_LEXICAL_RETRIEVER],
        similarity_top_k=20,
        num_queries=1,
        mode="reciprocal_rerank",
        use_async=True,
        verbose=False
    )
    
    return ensemble_retriever


def _parse_filters_to_llamaindex(filtros: dict):
    """Convierte tu dict de filtros al formato MetadataFilters de LlamaIndex."""
    from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
    
    li_filters = []
    
    if leg := filtros.get("legislatura"):
        li_filters.append(MetadataFilter(key="legislatura", value=leg))
        
    if orador := filtros.get("orador"):
        # Chroma suele soportar filtros exactos, para parciales es mejor la rama léxica
        li_filters.append(MetadataFilter(key="orador", value=orador))

    if ns := filtros.get("num_sesion"):
        li_filters.append(MetadataFilter(key="num_sesion", value=int(ns)))
        
    if not li_filters:
        return None
        
    return MetadataFilters(filters=li_filters)
