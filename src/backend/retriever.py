"""
retriever.py — Búsqueda Híbrida Simplificada para DiSeCan.
"""
from __future__ import annotations
from typing import List
from llama_index.core import VectorStoreIndex, QueryBundle
from llama_index.core.retrievers import BaseRetriever, VectorIndexRetriever, QueryFusionRetriever
from llama_index.core.schema import NodeWithScore, TextNode
from backend.chroma_store import get_all_chunks
from backend.db import linguistic_search
from backend.query_analyzer import SearchPlan

class ILRetriever(BaseRetriever):
    """
    ILRetriever (Index Lexicographical): Independiente y especializado en MySQL.
    """
    def __init__(self, chroma_chunks: list[dict], plan: SearchPlan, similarity_top_k: int = 25):
        self._top_k = similarity_top_k
        self._plan = plan
        # Mapeo directo por ID de chunk para recuperar el contenido completo
        self._chunk_map = {c["id"]: c for c in chroma_chunks}
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        # Extraer términos del plan agéntico
        # Priorizamos frases secuenciales y términos literales + conceptos semánticos
        search_terms = self._plan.sequential_phrases + self._plan.literal_terms + self._plan.semantic_concepts
        
        if not search_terms:
            return []

        # Búsqueda léxica (Lingüística) en MySQL al estilo DiSeCan - Independiente del Vector Store
        sql_results = linguistic_search(search_terms, top_k=self._top_k)
        
        results = []
        for res in sql_results:
            # Reconstruir el ID determinista
            target_id = f"c_{res['id_documento']}_{res['id_frase']}"
            
            if target_id in self._chunk_map:
                c = self._chunk_map[target_id]
                node = TextNode(
                    text=c["document"], 
                    id_=c["id"], 
                    metadata=c["metadata"]
                )
                # El score léxico es la cantidad de lemas coincidentes
                results.append(NodeWithScore(node=node, score=float(res.get("score", 1.0))))
        
        return results[:self._top_k]

def get_ensemble_retriever(index: VectorStoreIndex, plan: SearchPlan, filtros: dict | None = None) -> BaseRetriever:
    # 1. Retriever Semántico (usa HyDE indirectamente vía QueryBundle en orchestrator)
    vector_retriever = VectorIndexRetriever(index=index, similarity_top_k=20)
    
    # 2. Obtener chunks para el mapeo del ILRetriever
    chroma_chunks = get_all_chunks()
    
    if not chroma_chunks:
        return vector_retriever

    # 3. ILRetriever independiente (usa el plan agéntico para SQL)
    lexical_retriever = ILRetriever(chroma_chunks, plan)

    # 4. Fusión de resultados (RRF)
    # Esto ejecuta ambos retrievers de forma independiente y combina los resultados
    return QueryFusionRetriever(
        [vector_retriever, lexical_retriever],
        similarity_top_k=10,
        num_queries=1,
        mode="reciprocal_rerank",
        use_async=False
    )
