"""
orchestrator.py — Orquestador central de LlamaIndex (Versión Simplificada).
"""
from __future__ import annotations
import logging
import os
from llama_index.core import Settings, StorageContext, VectorStoreIndex, get_response_synthesizer, PromptTemplate
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.llms.ollama import Ollama
from llama_index.vector_stores.chroma import ChromaVectorStore
from backend.chroma_store import get_collection
from backend.retriever import get_ensemble_retriever
from backend.embedder import embed_query, embed_passages
from backend.query_analyzer import QueryAnalyzer, SearchPlan
from backend.byte_reader import fix_encoding, ByteTextReader
from backend.reranker import LLMReranker

logger = logging.getLogger("disecan.orchestrator")

STOPWORDS = {
    "que", "de", "se", "el", "la", "a", "en", "y", "o", "un", "una", 
    "los", "las", "por", "con", "no", "su", "sus", "para", "como", 
    "al", "lo", "del", "qué", "cuál", "cuáles", "quién", "quiénes",
    "donde", "cuando", "esta", "este", "estos", "estas", "han", "ha", 
    "hay", "es", "son", "fue", "eran"
}

import torch

def setup_settings():
    # Forzamos CPU para dejar la VRAM (cuda) libre exclusivamente para Ollama
    device = "cpu"
    logger.info(f"[Orchestrator] Configurando LlamaIndex en dispositivo: {device}")
    
    os.environ["OPENAI_API_KEY"] = "sk-no-key-required"
    Settings.embed_model = type('CustomEmbedder', (BaseEmbedding,), {
        '_get_query_embedding': lambda self, q: embed_query(q, device=device),
        '_get_text_embedding': lambda self, t: embed_passages([t], device=device)[0],
        '_get_text_embeddings': lambda self, ts: embed_passages(ts, device=device),
        '_aget_query_embedding': lambda self, q: self._get_query_embedding(q),
        '_aget_text_embedding': lambda self, t: self._get_text_embedding(t)
    })()
    Settings.llm = Ollama(model="qwen2.5:3b", base_url="http://localhost:11434", request_timeout=600.0)

setup_settings()

QA_PROMPT = PromptTemplate(
    "Eres el Asistente Analítico del Parlamento de Canarias. Responde basado en el contexto:\n"
    "{context_str}\n\nPregunta: {query_str}\n\nRespuesta estructurada (usa viñetas si hay listas):"
)

# Singletons
_ANALYZER = QueryAnalyzer()
_RERANKER = LLMReranker()

def get_query_engine(plan: SearchPlan, filtros: dict | None = None):
    """Inicializa el motor de consulta con el retriever híbrido configurado por el plan."""
    collection = get_collection()
    index = VectorStoreIndex.from_vector_store(ChromaVectorStore(chroma_collection=collection))
    
    # El ensemble_retriever ahora recibirá el plan (HyDE + Términos)
    retriever = get_ensemble_retriever(index, plan, filtros)
    
    query_engine = RetrieverQueryEngine(
        retriever=retriever,
        response_synthesizer=get_response_synthesizer(response_mode="compact")
    )
    query_engine.update_prompts({"response_synthesizer:text_qa_template": QA_PROMPT})
    return query_engine

def ask_disecan(query: str, filtros: dict | None = None, mode: str = "full"):
    """
    Pipeline RAG completo.

    Parámetros
    ----------
    query   : Pregunta del usuario en lenguaje natural.
    filtros : Filtros opcionales (legislatura, fecha_desde, fecha_hasta).
    mode    : "full"             → pipeline híbrido (vector + léxico + reranking).
              "linguistics_only" → solo búsqueda léxica SQL (sin ChromaDB ni HyDE).
    """

    logger.info(f"[Orchestrator] NUEVA PETICIÓN | mode='{mode}' | filtros={filtros}")
    logger.info(f"[Orchestrator] Query: '{query}'")

    # Analizar y convertir la query del usuario en un plan de búsqueda.
    logger.info("[Orchestrator] FASE 1: QueryAnalyzer")
    plan = _ANALYZER.analyze(query)
    logger.debug(f"[Orchestrator]   SearchPlan intent='{plan.intent}' | concepts={plan.semantic_concepts}")

    # Construir un objeto que pueda ser utilizado por LlamaIndex
    logger.info("[Orchestrator] FASE 2: QueryBundle")

    query_bundle = QueryBundle(
        query_str=query,  # Sí estamos en modo SQL solo pasamos la query original
        custom_embedding_strs=[plan.hypothetical_answer] if (mode == "full" and plan.hypothetical_answer) else None
    )

    # FASE 3: Recuperación 
    logger.info("[Orchestrator] FASE 3: Recuperación híbrida")
    collection = get_collection()
    # Obtener el la colección de vectores de Chroma para crear un índice de busqueda para vectores
    index = VectorStoreIndex.from_vector_store(ChromaVectorStore(chroma_collection=collection))
    retriever = get_ensemble_retriever(index, plan, filtros, mode=mode)

    # Recuperar los fragmentos de texto iniciales (nodos)
    initial_nodes = retriever.retrieve(query_bundle)
    logger.info(f"[Orchestrator]   Nodos recuperados (pre-reranking): {len(initial_nodes)}")
    for i, n in enumerate(initial_nodes[:5]):
        meta = n.node.metadata
        logger.debug(
            f"[Orchestrator]     [{i}] score={round(float(n.score or 0), 4):.4f} | "
            f"orador='{meta.get('orador', '?')}' | id={n.node.id_}"
        )

    # FASE 4: Re-ranking 
    logger.info("[Orchestrator] FASE 4: Re-ranking")
    if mode == "linguistics_only":
        logger.info("[Orchestrator]   Saltando re-ranking en modo 'linguistics_only' para conservar orden de BD.")
        reranked_nodes = initial_nodes[:10]
    else:
        logger.debug(f"[Orchestrator]   Aplicando re-ranking a {len(initial_nodes)} candidatos...")
        reranked_nodes = _RERANKER.rerank(query, initial_nodes)
        logger.info(f"[Orchestrator]   Nodos tras re-ranking: {len(reranked_nodes)}")

    # FASE 5: Síntesis de respuesta 
    logger.info("[Orchestrator] FASE 5: Síntesis de respuesta")
    # Si es solo SQL, la respuesta es sencillamente si ha habido coincidencias o no
    if mode == "linguistics_only":
        logger.info("[Orchestrator]   Saltando síntesis por LLM en modo 'linguistics_only'. Generando respuesta.")
        num_coincidencias = len(initial_nodes)
        if num_coincidencias > 0:
            response_text = f"Búsqueda lingüística finalizada. Se han encontrado {num_coincidencias} coincidencia(s) en los documentos para el patrón '{query}'."
        else:
            response_text = f"No se han encontrado coincidencias en los documentos para el patrón '{query}'."
        
        response = type("ProgrammaticResponse", (object,), {
            "response": response_text,
            "__str__": lambda self: response_text
        })()
    else:
        # En modo normal, LlamaIndex realiza la respuesta final con un sintetizador
        synthesizer = get_response_synthesizer(response_mode="compact")
        synthesizer.update_prompts({"text_qa_template": QA_PROMPT})
        # Necesita la query original y los fragmentos (nodos) para generar la respuesta final
        response = synthesizer.synthesize(query_bundle, nodes=reranked_nodes)
    
    # Devolvemos los términos usados para que el usuario pueda evaluarlos
    keywords = list(set(plan.semantic_concepts + plan.literal_terms + plan.sequential_phrases))

    _reader = ByteTextReader()
    sources = []
    for node in reranked_nodes:
        meta = node.metadata

        # FRASE CORTA: se lee de Frases.txt usando los offsets guardados en metadata
        b_frase_start = int(meta.get("b_frase_start", 0))
        b_frase_len   = int(meta.get("b_frase_len", 0))
        res = _reader.get_sentence_and_paragraph_offsets(b_frase_start, b_frase_len)
        sentence = res["sentence"] if res["sentence"] else node.get_content().strip()

        # PÁRRAFO CONTEXTO: se lee de Documentos.txt usando los offsets guardados en metadata
        b_par_start = int(meta.get("b_par_start", 0))
        b_par_len   = int(meta.get("b_par_len",   0))
        paragraph   = _reader.get_paragraph(b_par_start, b_par_len) if b_par_len > 0 else ""

        sources.append({
            "fragment":   sentence,                                      # Frase corta visible
            "context":    paragraph,                                     # Párrafo ampliado (al expandir)
            "speaker":    fix_encoding(meta.get("orador", "Desconocido")),
            "date":       meta.get("fecha", ""),
            "legislature": meta.get("legislatura", ""),
            "score":      round(float(node.score or 0.0) * 100, 1),
            "id":         node.id_
        })

    logger.info(f"[Orchestrator] RESPUESTA GENERADA | Fuentes: {len(sources)} | Modo: '{mode}'")
    logger.debug(f"[Orchestrator] Keywords devueltas: {list(set(keywords))}")

    return str(response), sources, list(set(keywords))
