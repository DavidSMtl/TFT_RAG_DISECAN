"""
retriever.py — Búsqueda Híbrida Simplificada para DiSeCan.
"""
from __future__ import annotations
import logging
import re
from llama_index.core import VectorStoreIndex, QueryBundle
from llama_index.core.retrievers import BaseRetriever, VectorIndexRetriever, QueryFusionRetriever
from llama_index.core.schema import NodeWithScore, TextNode
from backend.chroma_store import get_chunks_by_ids
from backend.db import linguistic_search
from backend.query_analyzer import SearchPlan

logger = logging.getLogger("disecan.retriever")

class ILRetriever(BaseRetriever):
    """
    ILRetriever (Index Lexicographical): Independiente y especializado en MySQL.
    """
    def __init__(self, plan: SearchPlan, similarity_top_k: int = 25):
        self._top_k = similarity_top_k
        self._plan = plan
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        raw_query = query_bundle.query_str.strip()

        # Si hay sintaxis de DiSeCan, buscar por ella exacta.
        if re.search(r"[<>\[\]:\*\?]", raw_query):
            search_terms = [raw_query]
        else:
            search_terms = list(set(
                self._plan.sequential_phrases + 
                self._plan.literal_terms + 
                self._plan.semantic_concepts
            ))

        if not search_terms:
            return []

        # 1. Búsqueda en MySQL
        sql_results = linguistic_search(search_terms, top_k=self._top_k)
        if not sql_results:
            return []

        # 2. Reconstrucción de documentos vía ChromaDB usando el mapeo de IDs
        target_ids = [f"c_{res['id_documento']}_{res['id_frase']}" for res in sql_results]
        fetched_chunks = get_chunks_by_ids(target_ids)
        chunk_map = {c["id"]: c for c in fetched_chunks}
        
        results = []
        for res in sql_results:
            tid = f"c_{res['id_documento']}_{res['id_frase']}"
            if tid in chunk_map:
                c = chunk_map[tid]
                node = TextNode(text=c["document"], id_=c["id"], metadata=c["metadata"])
                results.append(NodeWithScore(node=node, score=float(res.get("score", 1.0))))

        logger.info(f"[Retriever/SQL] Nodos léxicos devueltos: {len(results)}")
        return results[:self._top_k]


def get_ensemble_retriever(
    index: VectorStoreIndex,
    plan: SearchPlan,
    filtros: dict | None = None,
    mode: str = "full"
) -> BaseRetriever:
    """
    Crea el retriever apropiado según el modo.
    """
    if mode == "linguistics_only":
        return ILRetriever(plan)

    # Retriever Híbrido: Vectorial + SQL (Léxico) fusionados con RRF
    vector_retriever = VectorIndexRetriever(index=index, similarity_top_k=20)
    lexical_retriever = ILRetriever(plan)

    return QueryFusionRetriever(
        [vector_retriever, lexical_retriever],
        similarity_top_k=10,
        num_queries=1,
        mode="reciprocal_rerank",
        use_async=False
    )
