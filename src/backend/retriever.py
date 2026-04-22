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

class SQLLexicalRetriever(BaseRetriever):
    """
    Retriever léxico que busca en MySQL y lo mapea a chunks de ChromaDB.
    """
    def __init__(self, chroma_chunks: list[dict], similarity_top_k: int = 20):
        self._chunks = chroma_chunks
        self._top_k = similarity_top_k
        # Mapeo rápido: id_frase_inicio -> chunk
        self._chunk_map = {int(c["metadata"]["id_frase_inicio"]): c for c in chroma_chunks if "id_frase_inicio" in c["metadata"]}
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        # En este modelo simplificado, asumimos que la query ya viene limpia o lematizada
        # Para simplificar al máximo, usamos una búsqueda por lemas básica
        query = query_bundle.query_str
        
        # Simulación de extracción de lemas (en producción usar lemmatizer.get_lemas)
        from backend.lemmatizer import get_lemas
        lemas = get_lemas(query)
        
        sql_results = lexical_search_chunks(lemas, top_k=self._top_k)
        
        results = []
        for res in sql_results:
            fid = res["id_frase"]
            if fid in self._chunk_map:
                c = self._chunk_map[fid]
                node = TextNode(text=c["document"], id_=c["id"], metadata=c["metadata"])
                results.append(NodeWithScore(node=node, score=1.0)) # Score binario para léxico en esta versión
        
        return results[:self._top_k]

def get_ensemble_retriever(index: VectorStoreIndex, filtros: dict | None = None) -> BaseRetriever:
    vector_retriever = VectorIndexRetriever(index=index, similarity_top_k=20)
    chroma_chunks = get_all_chunks()
    
    if not chroma_chunks:
        return vector_retriever

    lexical_retriever = SQLLexicalRetriever(chroma_chunks)
    
    return QueryFusionRetriever(
        [vector_retriever, lexical_retriever],
        similarity_top_k=7,
        num_queries=1,
        mode="reciprocal_rerank",
        use_async=False
    )
