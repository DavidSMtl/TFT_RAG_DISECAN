"""
orchestrator.py — Orquestador central de LlamaIndex.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

from llama_index.core import (
    Settings,
    StorageContext,
    VectorStoreIndex,
    get_response_synthesizer,
    PromptTemplate,
)
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.llms.ollama import Ollama
from llama_index.vector_stores.chroma import ChromaVectorStore

from backend.chroma_store import get_collection
from backend.retriever import get_ensemble_retriever
from backend.embedder import embed_query, embed_passages

load_dotenv()

# ── Configuración Global ───────────────────────────────────────────────────

EMBED_MODEL_NAME = "intfloat/multilingual-e5-base"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").replace("/v1", "")

class CustomEmbedder(BaseEmbedding):
    """
    Clase personalizada para LlamaIndex que reutiliza nuestra lógica de 
    embedder.py (sentence-transformers), evitando errores de caché en Windows.
    """
    def _get_query_embedding(self, query: str) -> list[float]:
        return embed_query(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        # Para un solo texto, devolvemos el primer resultado
        return embed_passages([text])[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return embed_passages(texts)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)

def setup_settings():
    """Configura los modelos por defecto para todo LlamaIndex."""
    print(f"[Orchestrator] Configurando Embeddings: {EMBED_MODEL_NAME}")
    # Usamos nuestra clase que ya comprobamos que funciona en la ingestión
    Settings.embed_model = CustomEmbedder()
    
    print(f"[Orchestrator] Configurando LLM Local (Ollama): {OLLAMA_MODEL}")
    Settings.llm = Ollama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, request_timeout=300.0)
    Settings.chunk_size = 1024

# ── Prompts ────────────────────────────────────────────────────────────────

QA_PROMPT_STR = (
    "Contexto extraído del Diario de Sesiones del Parlamento de Canarias:\n"
    "---------------------\n"
    "{context_str}\n"
    "---------------------\n"
    "Dada la información anterior, responde a la siguiente pregunta: {query_str}\n"
    "Instrucciones:\n"
    "1. Responde siempre en ESPAÑOL.\n"
    "2. Si la respuesta no está en el contexto, di simplemente 'Lo siento, no he encontrado información detallada sobre ese tema en el Diario de Sesiones'.\n"
    "3. Sé preciso y cita oradores si están disponibles.\n"
    "Respuesta:"
)
QA_PROMPT = PromptTemplate(QA_PROMPT_STR)

def get_query_engine(filtros: dict | None = None):
    """Construye y devuelve el motor de consulta RAG asíncrono."""
    setup_settings()
    
    collection = get_collection()
    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    
    index = VectorStoreIndex.from_vector_store(
        vector_store, storage_context=storage_context
    )
    
    ensemble_retriever = get_ensemble_retriever(index, filtros)
    response_synthesizer = get_response_synthesizer(response_mode="compact")
    
    query_engine = RetrieverQueryEngine(
        retriever=ensemble_retriever,
        response_synthesizer=response_synthesizer,
        node_postprocessors=[] # Eliminamos el filtro de 0.5 para ver resultados
    )
    
    # Aplicar el prompt en español
    query_engine.update_prompts({"response_synthesizer:text_qa_template": QA_PROMPT})
    
    return query_engine

async def ask_disecan(query: str, filtros: dict | None = None):
    """Realiza la búsqueda híbrida y genera la respuesta."""
    engine = get_query_engine(filtros)
    
    print(f"[Orchestrator] Procesando consulta: '{query}'...")
    response = await engine.aquery(query)
    
    print(f"[Orchestrator] Recuperados {len(response.source_nodes)} fragmentos.")
    
    sources = []
    for node in response.source_nodes:
        meta = node.metadata
        print(f"  - Fragmento de {meta.get('orador')} (Score: {node.score:.4f})")
        
        # Generar URL del PDF (Simulado basado en legislatura y nombre de fichero)
        leg = meta.get("legislatura", "X")
        pdf_name = meta.get("pdf_file", "")
        # URL base típica del Parlamento de Canarias (ajustar si es necesario)
        pdf_url = f"https://www.parcan.es/publicaciones/diarios/{leg}/{pdf_name}" if pdf_name else "#"

        sources.append({
            "fragment": node.get_content(),
            "speaker": meta.get("orador", "Desconocido"),
            "date": meta.get("fecha", ""),
            "legislature": leg,
            "pdf_url": pdf_url,
            "score": float(node.score or 0.0)
        })
        
    if not str(response).strip():
        print("[Orchestrator] ADVERTENCIA: La respuesta del LLM está vacía.")
        
    return str(response), sources
