"""
retriever.py — Búsqueda Híbrida Simplificada para DiSeCan.
"""
from __future__ import annotations
import logging
import re
from typing import List
from llama_index.core import VectorStoreIndex, QueryBundle
from llama_index.core.retrievers import BaseRetriever, VectorIndexRetriever, QueryFusionRetriever
from llama_index.core.schema import NodeWithScore, TextNode
from backend.chroma_store import get_all_chunks
from backend.db import linguistic_search
from backend.query_analyzer import SearchPlan

# ── Logger ────────────────────────────────────────────────────────────────────
logger = logging.getLogger("disecan.retriever")

class ILRetriever(BaseRetriever):
    """
    ILRetriever (Index Lexicographical): Independiente y especializado en MySQL.
    Soporta tanto búsqueda libre como patrones DISECAN (<cat>, [lema], etc.).
    """
    def __init__(self, chroma_chunks: list[dict], plan: SearchPlan, similarity_top_k: int = 25):
        self._top_k = similarity_top_k
        self._plan = plan
        # Mapeo directo por ID de chunk para recuperar el contenido completo
        self._chunk_map = {c["id"]: c for c in chroma_chunks}
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        raw_query = query_bundle.query_str.strip()

        # ── Determinar los términos de búsqueda ──────────────────────────────
        # Si la query raw contiene sintaxis DISECAN, la usamos directamente
        # para no perder los patrones al pasar por el QueryAnalyzer.
        has_disecan = bool(re.search(r"[<>\[\]:\*\?]", raw_query))
        if has_disecan:
            search_terms = [raw_query]
            logger.info(f"[Retriever/SQL] Sintaxis DISECAN detectada — usando query raw: '{raw_query}'")
        else:
            # Búsqueda libre: extraer del plan agéntico
            search_terms = list(set(
                self._plan.sequential_phrases
                + self._plan.literal_terms
                + self._plan.semantic_concepts
            ))

        logger.info(f"[Retriever/SQL] ── BÚSQUEDA LÉXICA ({'─' * 25})")
        logger.debug(f"[Retriever/SQL]   Términos de búsqueda: {search_terms}")

        if not search_terms:
            logger.warning("[Retriever/SQL]   ✗ Sin términos de búsqueda — devolviendo vacío.")
            return []

        # Búsqueda léxica (Lingüística) en MySQL al estilo DiSeCan
        sql_results = linguistic_search(search_terms, top_k=self._top_k)

        logger.debug(f"[Retriever/SQL]   SQL devolvió {len(sql_results)} filas.")
        if sql_results:
            top3 = [(r["id_frase"], r["id_documento"], round(r.get("score", 0), 3)) for r in sql_results[:3]]
            logger.debug(f"[Retriever/SQL]   Top-3 (id_frase, id_doc, score): {top3}")

        results = []
        matched = 0
        unmatched_ids = []
        for res in sql_results:
            # Reconstruir el ID determinista
            target_id = f"c_{res['id_documento']}_{res['id_frase']}"

            if target_id in self._chunk_map:
                matched += 1
                c = self._chunk_map[target_id]
                node = TextNode(
                    text=c["document"],
                    id_=c["id"],
                    metadata=c["metadata"]
                )
                results.append(NodeWithScore(node=node, score=float(res.get("score", 1.0))))
            else:
                unmatched_ids.append(target_id)

        logger.debug(f"[Retriever/SQL]   Match en chroma_map: {matched}/{len(sql_results)} chunks encontrados.")
        if unmatched_ids:
            logger.debug(f"[Retriever/SQL]   IDs sin match (primeros 5): {unmatched_ids[:5]}")
        logger.info(f"[Retriever/SQL]   Nodos léxicos devueltos: {len(results[:self._top_k])}")
        logger.debug(f"[Retriever/SQL] {'─' * 50}")

        return results[:self._top_k]

def get_ensemble_retriever(
    index: VectorStoreIndex,
    plan: SearchPlan,
    filtros: dict | None = None,
    mode: str = "full"
) -> BaseRetriever:
    """
    Crea el retriever apropiado según el modo:
      - "full"             → Híbrido: VectorIndexRetriever (semántico) + ILRetriever (léxico) fusionados con RRF.
      - "linguistics_only" → Solo ILRetriever (búsqueda léxica SQL), sin ChromaDB ni HyDE.
    """
    logger.info(f"[Retriever]   MODO de recuperación: '{mode}'")

    # 1. Obtener chunks para el mapeo del ILRetriever
    chroma_chunks = get_all_chunks()

    if mode == "linguistics_only":
        logger.info("[Retriever]   ✔ Modo linguistics_only: usando solo ILRetriever (SQL DiSeCan).")
        if not chroma_chunks:
            logger.warning("[Retriever]   ✗ chroma_chunks vacío — no se puede construir chunk_map para ILRetriever.")
        return ILRetriever(chroma_chunks or [], plan)

    # Modo full: retriever híbrido
    # 2. Retriever Semántico (usa HyDE indirectamente vía QueryBundle en orchestrator)
    vector_retriever = VectorIndexRetriever(index=index, similarity_top_k=20)
    logger.debug(f"[Retriever]   VectorIndexRetriever: similarity_top_k=20")

    if not chroma_chunks:
        logger.warning("[Retriever]   ✗ chroma_chunks vacío — devolviendo solo vector_retriever.")
        return vector_retriever

    # 3. ILRetriever independiente (usa el plan agéntico para SQL)
    lexical_retriever = ILRetriever(chroma_chunks, plan)

    # 4. Fusión de resultados (RRF)
    # Esto ejecuta ambos retrievers de forma independiente y combina los resultados
    logger.debug("[Retriever]   QueryFusionRetriever (RRF): VectorIndex + ILRetriever, top_k=10, num_queries=1")
    return QueryFusionRetriever(
        [vector_retriever, lexical_retriever],
        similarity_top_k=10,
        num_queries=1,
        mode="reciprocal_rerank",
        use_async=False
    )
