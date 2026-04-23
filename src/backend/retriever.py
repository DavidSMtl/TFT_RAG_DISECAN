"""
retriever.py — Búsqueda Híbrida Simplificada para DiSeCan.
"""
from __future__ import annotations
from typing import List
from llama_index.core import VectorStoreIndex, QueryBundle
from llama_index.core.retrievers import BaseRetriever, VectorIndexRetriever, QueryFusionRetriever
from llama_index.core.schema import NodeWithScore, TextNode
from backend.chroma_store import get_all_chunks
from backend.db import lexical_search_chunks

class ILRetriever(BaseRetriever):
    """
    ILRetriever (Index Lexicographical): Busca en MySQL (DiSeCan) 
    y cruza los resultados con ChromaDB usando IDs deterministas.
    """
    def __init__(self, chroma_chunks: list[dict], similarity_top_k: int = 25):
        self._top_k = similarity_top_k
        # Mapeo directo por ID de chunk para máxima velocidad
        self._chunk_map = {c["id"]: c for c in chroma_chunks}
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        query = query_bundle.query_str
        
        # Obtener lemas de la consulta para buscar en MySQL
        from backend.lemmatizer import get_lemas
        lemas = get_lemas(query)
        
        # Búsqueda léxica en MySQL (devuelve id_frase e id_documento)
        sql_results = lexical_search_chunks(lemas, top_k=self._top_k)
        
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

def get_ensemble_retriever(index: VectorStoreIndex, filtros: dict | None = None) -> BaseRetriever:
    vector_retriever = VectorIndexRetriever(index=index, similarity_top_k=20)
    chroma_chunks = get_all_chunks()
    
    if not chroma_chunks:
        return vector_retriever

    lexical_retriever = ILRetriever(chroma_chunks)

    
    return QueryFusionRetriever(
        [vector_retriever, lexical_retriever],
        similarity_top_k=7,
        num_queries=1,
        mode="reciprocal_rerank",
        use_async=False
    )
