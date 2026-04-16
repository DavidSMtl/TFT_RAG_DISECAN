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

def get_ensemble_retriever(index: VectorStoreIndex, filtros: dict | None = None) -> BaseRetriever:
    """
    Crea un QueryFusionRetriever que combina la búsqueda semántica y léxica.
    
    Args:
        index   : Índice de LlamaIndex vinculado a ChromaDB.
        filtros : Filtros de metadatos (opcional).
    """
    
    # 1. Rama Semántica
    # Aplicamos filtros de metadatos si vienen (LlamaIndex los traduce a Chroma where)
    vector_retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=20,
        filters=_parse_filters_to_llamaindex(filtros) if filtros else None
    )
    
    # 2. Rama Léxica (BM25)
    # Nota: LlamaIndex BM25Retriever construye el índice desde los nodos del index
    # Esto es ideal porque ya tenemos los párrafos en el índice.
    lexical_retriever = BM25Retriever.from_defaults(
        index=index,
        similarity_top_k=20,
    )
    
    # 3. Fusión por RRF (Reciprocal Rank Fusion)
    # LlamaIndex maneja la ejecución en paralelo y la fusión de forma nativa
    ensemble_retriever = QueryFusionRetriever(
        [vector_retriever, lexical_retriever],
        similarity_top_k=10,
        num_queries=1,  # Solo la query original, sin parafraseo
        mode="reciprocal_rerank", # RRF
        use_async=True,
        verbose=True
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
