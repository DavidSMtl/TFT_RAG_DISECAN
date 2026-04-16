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

def get_ensemble_retriever(index: VectorStoreIndex, filtros: dict | None = None) -> BaseRetriever:
    """
    Crea un QueryFusionRetriever que combina la búsqueda semántica y léxica.
    """
    
    # 1. Rama Semántica (Consulta directa a Chroma)
    vector_retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=20,
        filters=_parse_filters_to_llamaindex(filtros) if filtros else None
    )
    
    # 2. Rama Léxica (BM25)
    # IMPORTANTE: Al cargar desde Chroma persistente, el index no tiene los nodos en memoria.
    # Tenemos que recuperarlos para construir el índice BM25.
    print("[Retriever] Recuperando documentos para el índice BM25...")
    chunks = get_all_chunks()
    nodes = [
        TextNode(text=c["document"], id_=c["id"], metadata=c["metadata"]) 
        for c in chunks
    ]
    
    if not nodes:
        print("[Retriever] ADVERTENCIA: No hay documentos para BM25. Usando solo rama semántica.")
        return vector_retriever

    lexical_retriever = BM25Retriever.from_defaults(
        nodes=nodes,
        similarity_top_k=20,
    )
    
    # 3. Fusión por RRF (Reciprocal Rank Fusion)
    print(f"[Retriever] Ejecutando búsqueda híbrida (Semántica + BM25) para top_k=10...")
    
    ensemble_retriever = QueryFusionRetriever(
        [vector_retriever, lexical_retriever],
        similarity_top_k=10,
        num_queries=1,
        mode="reciprocal_rerank",
        use_async=True,
        verbose=True  # Activamos el verbose de LlamaIndex para más info
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
