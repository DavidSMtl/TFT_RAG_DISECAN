"""
orchestrator.py — Orquestador central de LlamaIndex.

Configura el motor de consulta RAG unificando:
1. Almacenamiento Vectorial (ChromaDB)
2. Modelo de Embeddings Local (HuggingFace)
3. Modelo LLM Local (Ollama / vLLM)
"""
from __future__ import annotations

import os
from pathlib import Path

from llama_index.core import (
    Settings,
    StorageContext,
    VectorStoreIndex,
    get_response_synthesizer,
)
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from backend.chroma_store import get_collection
from backend.retriever import get_ensemble_retriever

# ── Configuración Global de LlamaIndex (Settings) ──────────────────────────

# 1. Embedding Model (debe coincidir con el usado en la ingesta)
# multilingual-e5-base suele mapearse a intfloat/multilingual-e5-base
EMBED_MODEL_NAME = "intfloat/multilingual-e5-base"

# 2. LLM Model (Ollama por defecto para ejecución local)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

def setup_settings():
    """Configura los modelos por defecto para todo LlamaIndex."""
    print(f"[Orchestrator] Configurando Embeddings: {EMBED_MODEL_NAME}")
    Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    
    print(f"[Orchestrator] Configurando LLM Local (Ollama): {OLLAMA_MODEL}")
    Settings.llm = Ollama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, request_timeout=120.0)
    
    # Tamaño de chunk no es crítico aquí porque ya vienen pre-chunked de la DB,
    # pero ayuda a la coherencia interna de LlamaIndex.
    Settings.chunk_size = 1024


def get_query_engine(filtros: dict | None = None):
    """
    Construye y devuelve el motor de consulta RAG asíncrono.
    
    Integra el Ensemble Retriever (Léxico + Semántico) y el sintetizador de respuesta.
    """
    setup_settings()
    
    # 1. Preparar el Vector Store (Chroma)
    collection = get_collection()
    vector_store = ChromaVectorStore(chroma_collection=collection)
    
    # 2. Reperar el Storage Context
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    
    # 3. Cargar el índice (sin necesidad de re-insertar, ya está en Chroma)
    index = VectorStoreIndex.from_vector_store(
        vector_store, storage_context=storage_context
    )
    
    # 4. Obtener el Ensemble Retriever personalizado (Híbrido)
    # Este viene de retriever.py y ya maneja las dos ramas paralelas
    ensemble_retriever = get_ensemble_retriever(index, filtros)
    
    # 5. Configurar el Sintetizador de respuesta (Grounding)
    response_synthesizer = get_response_synthesizer(
        response_mode="compact", # Refina y compacta el contexto
    )
    
    # 6. Crear el Query Engine
    query_engine = RetrieverQueryEngine(
        retriever=ensemble_retriever,
        response_synthesizer=response_synthesizer,
        node_postprocessors=[
            SimilarityPostprocessor(similarity_cutoff=0.5) # Filtro de calidad opcional
        ]
    )
    
    return query_engine

async def ask_disecan(query: str, filtros: dict | None = None):
    """
    Punto de entrada asíncrono para el chat.
    Realiza la búsqueda híbrida y genera la respuesta.
    """
    engine = get_query_engine(filtros)
    response = await engine.aquery(query)
    
    # Formatear fuentes para la UI
    sources = []
    for node in response.source_nodes:
        meta = node.metadata
        sources.append({
            "fragment": node.get_content(),
            "speaker": meta.get("orador", "Desconocido"),
            "date": meta.get("fecha", ""),
            "legislature": meta.get("legislatura", ""),
            "pdf_url": "#", # Placeholder para link al PDF real
            "score": float(node.score or 0.0)
        })
        
    return str(response), sources
