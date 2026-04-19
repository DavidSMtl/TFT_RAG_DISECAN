"""
retriever.py — Búsqueda Híbrida: Semántica (ChromaDB) + Léxica (MySQL DiSeCan).

Arquitectura:
    1. VectorIndexRetriever   → búsqueda semántica por embeddings en ChromaDB
    2. SQLLexicalRetriever    → búsqueda léxica por lemas directamente en MySQL
       - Busca los lemas de la query en la tabla `palabras`
       - Identifica qué frases (id_frase) los contienen
       - Localiza el chunk de ChromaDB que contiene esas frases (via metadata)
       - Devuelve NodeWithScore ← misma "moneda" que el retriever semántico

    3. QueryFusionRetriever   → fusiona ambos resultados con RRF
"""
from __future__ import annotations

import re
import json
from typing import List

from llama_index.core import VectorStoreIndex, QueryBundle
from llama_index.core.retrievers import (
    BaseRetriever,
    VectorIndexRetriever,
    QueryFusionRetriever,
)
from llama_index.core.schema import NodeWithScore, TextNode

from backend.chroma_store import get_all_chunks
from backend.db import lexical_search_chunks, lexical_search_advanced
from backend.lemmatizer import get_lemas
from backend.query_analyzer import SearchPlan


# SQL Lexical Retriever 


class SQLLexicalRetriever(BaseRetriever):
    """
    Retriever léxico que busca lemas en MySQL y devuelve los chunks de
    ChromaDB que contienen esas frases, como NodeWithScore.

    Flujo:
        query → tokens/lemas → MySQL (WHERE lema IN (...)) → id_frase matches
        → localizar chunk en Chroma (id_frase_inicio <= id_frase <= id_frase_fin)
        → devolver NodeWithScore con score = n_matches / n_lemas
    """

    def __init__(
        self,
        chroma_chunks: list[dict],
        similarity_top_k: int = 20,
        filtros: dict | None = None,
    ):
        """
        Args:
            chroma_chunks   : lista de todos los chunks de ChromaDB (id, document, metadata)
            similarity_top_k: cuántos resultados devolver
            filtros         : filtros de legislatura/sesión (opcional)
        """
        self._chunks = chroma_chunks
        self._top_k = similarity_top_k
        self._filtros = filtros
        # Preconstruir índice: id_documento → list of chunk dicts
        # Para lookup eficiente de "qué chunk contiene la frase X"
        self._idx_by_doc: dict[int, list[dict]] = {}
        for c in chroma_chunks:
            doc_id = c["metadata"].get("id_documento")
            if doc_id is not None:
                self._idx_by_doc.setdefault(int(doc_id), []).append(c)
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        """Busca los fragmentos usando el plan de búsqueda (si viene en JSON) o lemas."""
        query = query_bundle.query_str
        
        # Intentar parsear como SearchPlan (pasado desde orchestrator)
        plan = None
        if query.startswith("{") and "must_have" in query:
            try:
                plan = SearchPlan(**json.loads(query))
            except:
                pass
        
        if not plan:
            lemas = get_lemas(query)
            plan = SearchPlan(semantic_concepts=lemas, intent="hybrid")
            print(f"[SQLLexical] Buscando lemas simples: {lemas}")
        else:
            # 1. Expandir solo conceptos semánticos y entidades usando el Lematizador
            # NO lematizamos secuenciales ni literales (perderíamos el orden/forma exacta)
            semantic_to_lematize = plan.semantic_concepts + plan.entities
            
            deep_lemas = []
            for term in semantic_to_lematize:
                deep_lemas.extend(get_lemas(term))
            
            plan.semantic_concepts = list(set(deep_lemas))
            print(f"[SQLLexical] Conceptos Lematizados: {plan.semantic_concepts}")
            if plan.sequential_phrases:
                print(f"[SQLLexical] Secuencias Protegidas: {plan.sequential_phrases}")
            if plan.literal_terms:
                print(f"[SQLLexical] Términos Literales: {plan.literal_terms}")

        # 2. Buscar frases que cumplen el plan (en MySQL)
        sql_matches = lexical_search_advanced(
            plan=plan,
            filtros=self._filtros,
            top_k=self._top_k,
        )

        if not sql_matches:
            print("[SQLLexical] Sin resultados léxicos en MySQL.")
            return []

        print(f"[SQLLexical] {len(sql_matches)} frases SQL encontradas.")

        # 2. Mapear cada frase SQL → chunk de Chroma
        #    Un chunk cubre [id_frase_inicio, id_frase_fin].
        #    Buscamos el chunk cuyo rango contiene la id_frase devuelta por SQL.
        chunk_scores: dict[str, float] = {}   # chunk_id → score acumulado
        chunk_nodes: dict[str, dict] = {}     # chunk_id → chroma chunk dict

        # Normalización de score base
        # Aseguramos casting a float para evitar errores con Decimal de MySQL
        max_sql_score = float(max([m["score"] for m in sql_matches])) if sql_matches else 1.0

        for match in sql_matches:
            id_frase: int = match["id_frase"]
            id_doc: int = match["id_documento"]
            sql_score: float = float(match["score"])

            # Score normalizado respecto al mejor resultado SQL
            score = sql_score / max_sql_score

            # Buscar el chunk que contiene esta frase
            for chunk in self._idx_by_doc.get(int(id_doc), []):
                meta = chunk["metadata"]
                inicio = meta.get("id_frase_inicio", 0)
                fin = meta.get("id_frase_fin", 0)
                if inicio <= id_frase <= fin:
                    cid = chunk["id"]
                    # Acumular score: si el chunk contiene varias frases relevantes,
                    # su score aumenta (suma logarítmica para no sobre-puntuar)
                    prev = chunk_scores.get(cid, 0.0)
                    chunk_scores[cid] = min(1.0, prev + score * 0.5)
                    chunk_nodes[cid] = chunk
                    break  # ya asignado el chunk

        if not chunk_nodes:
            print("[SQLLexical] Frases encontradas en MySQL pero sin chunk en Chroma.")
            return []

        # 3. Ordenar por score y devolver los top_k como NodeWithScore
        ranked = sorted(chunk_scores.items(), key=lambda x: x[1], reverse=True)
        results: list[NodeWithScore] = []

        for chunk_id, score in ranked[: self._top_k]:
            c = chunk_nodes[chunk_id]
            node = TextNode(
                text=c["document"],
                id_=chunk_id,
                metadata=c["metadata"],
            )
            results.append(NodeWithScore(node=node, score=score))

        print(f"[SQLLexical] {len(results)} chunks recuperados vía búsqueda léxica SQL.")
        return results


# Cache Global

_CACHED_CHROMA_CHUNKS: list[dict] | None = None


def _get_cached_chunks() -> list[dict]:
    """Carga todos los chunks de Chroma una sola vez (singleton)."""
    global _CACHED_CHROMA_CHUNKS
    if _CACHED_CHROMA_CHUNKS is None:
        print("[Retriever] Cargando chunks de ChromaDB para el retriever léxico...")
        _CACHED_CHROMA_CHUNKS = get_all_chunks()
        print(f"[Retriever] {len(_CACHED_CHROMA_CHUNKS)} chunks cargados.")
    return _CACHED_CHROMA_CHUNKS


# Ensemble Retriever 


def get_ensemble_retriever(
    index: VectorStoreIndex,
    filtros: dict | None = None,
) -> BaseRetriever:
    """
    Crea un QueryFusionRetriever que combina:
      - Búsqueda semántica (ChromaDB embeddings)
      - Búsqueda léxica (MySQL por lemas, estilo DiSeCan)

    La fusión usa RRF (Reciprocal Rank Fusion), que combina rankings
    sin depender de que los scores sean comparables entre sí.
    """
    # 1. Rama Semántica — Vector Store (ChromaDB)
    vector_retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=20,
        filters=_parse_filters_to_llamaindex(filtros) if filtros else None,
    )

    # 2. Rama Léxica — MySQL DiSeCan-style
    chroma_chunks = _get_cached_chunks()

    if not chroma_chunks:
        print("[Retriever] ChromaDB vacío — usando solo búsqueda semántica.")
        return vector_retriever

    sql_lexical_retriever = SQLLexicalRetriever(
        chroma_chunks=chroma_chunks,
        similarity_top_k=20,
        filtros=filtros,
    )

    # 3. Fusión RRF
    print("[Retriever] Ejecutando búsqueda híbrida (Semántica + Léxica SQL)...")

    ensemble_retriever = QueryFusionRetriever(
        [vector_retriever, sql_lexical_retriever],
        similarity_top_k=7,
        num_queries=1,               # No generar sub-queries extra
        mode="reciprocal_rerank",    # RRF
        use_async=False,             # Síncrono para evitar event-loop issues
        verbose=False,
    )

    return ensemble_retriever


# Helpers 


def _parse_filters_to_llamaindex(filtros: dict):
    """Convierte un dict de filtros al formato MetadataFilters de LlamaIndex."""
    from llama_index.core.vector_stores import (
        MetadataFilter,
        MetadataFilters,
    )

    li_filters = []

    if leg := filtros.get("legislatura"):
        li_filters.append(MetadataFilter(key="legislatura", value=leg))
    if orador := filtros.get("orador"):
        li_filters.append(MetadataFilter(key="orador", value=orador))
    if ns := filtros.get("num_sesion"):
        li_filters.append(MetadataFilter(key="num_sesion", value=int(ns)))

    if not li_filters:
        return None

    return MetadataFilters(filters=li_filters)
