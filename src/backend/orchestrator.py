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
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.llms.ollama import Ollama
from llama_index.vector_stores.chroma import ChromaVectorStore

from backend.chroma_store import get_collection
from backend.retriever import get_ensemble_retriever
from backend.embedder import embed_query, embed_passages

class ChronicNodePostprocessor(BaseNodePostprocessor):
    """Ordena los fragmentos recuperados cronológicamente."""
    def _postprocess_nodes(
        self, nodes: list[NodeWithScore], query_bundle: QueryBundle | None = None
    ) -> list[NodeWithScore]:
        # Ordenamos por fecha e id_frase_inicio para mantener secuencia del diálogo
        return sorted(
            nodes, 
            key=lambda x: (
                x.node.metadata.get("fecha", ""), 
                x.node.metadata.get("id_frase_inicio", 0)
            )
        )

load_dotenv()

# ── Configuración Estricta Local (Anti-OpenAI) ──────────────────────────────

EMBED_MODEL_NAME = "intfloat/multilingual-e5-base"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").replace("/v1", "")

# 1. Definir el Embedder Local (FORZADO A CPU para el chat)
class CustomEmbedder(BaseEmbedding):
    """Reutiliza nuestra lógica de sentence-transformers forzando CPU para liberar VRAM."""
    def _get_query_embedding(self, query: str) -> list[float]:
        return embed_query(query, device="cpu")
    
    def _get_text_embedding(self, text: str) -> list[float]:
        return embed_passages([text], device="cpu")[0]
    
    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return embed_passages(texts, device="cpu")
    
    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)
    
    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)

# 2. Configurar Settings GLOBALES antes de cualquier otra operación
def setup_settings():
    print(f"[Orchestrator] Forzando entorno 100% LOCAL")
    os.environ["OPENAI_API_KEY"] = "sk-no-key-required-local-only"
    
    Settings.embed_model = CustomEmbedder()
    Settings.llm = Ollama(
        model=OLLAMA_MODEL, 
        base_url=OLLAMA_BASE_URL, 
        request_timeout=600.0,
        temperature=0.1
    )
    Settings.chunk_size = 1024
    Settings.context_window = 4096

# Ejecutar configuración inmediatamente al importar el módulo
setup_settings()

# ── Prompts ────────────────────────────────────────────────────────────────

QA_PROMPT_STR = (
    "Eres un asistente especializado en el Diario de Sesiones del Parlamento de Canarias.\n"
    "A continuación tienes fragmentos literales de intervenciones parlamentarias:\n"
    "---------------------\n"
    "{context_str}\n"
    "---------------------\n"
    "Pregunta del usuario: {query_str}\n\n"
    "Instrucciones:\n"
    "1. Responde SIEMPRE en ESPAÑOL.\n"
    "2. Estructura tu respuesta en párrafos separados, uno por orador o tema.\n"
    "3. Cita el nombre del orador y la fecha cuando estén disponibles.\n"
    "4. Si la información no está en el contexto, responde exactamente: "
    "'No he encontrado información sobre ese tema en las sesiones disponibles.'\n"
    "5. NO inventes datos que no estén en el contexto.\n\n"
    "Respuesta:"
)
QA_PROMPT = PromptTemplate(QA_PROMPT_STR)

# ── Singleton para el motor RAG ─────────────────────────────────────────────

_QUERY_ENGINE = None

def get_query_engine(filtros: dict | None = None):
    """
    Devuelve el motor de consulta. 
    Si los filtros cambian, se reconstruye el retriever, pero Settings se mantiene.
    """
    global _QUERY_ENGINE
    
    # 1. Configurar Settings una sola vez
    if Settings.llm is None or Settings.embed_model is None:
        setup_settings()
    
    # Si hay filtros específicos, generamos un motor "ad-hoc" 
    # (esto es ligero ya que los modelos ya están cargados)
    if filtros:
        return _build_query_engine(filtros)
    
    # Si no hay filtros, usamos el motor global cacheado
    if _QUERY_ENGINE is None:
        _QUERY_ENGINE = _build_query_engine(None)
    
    return _QUERY_ENGINE

def _build_query_engine(filtros: dict | None = None):
    """Lógica interna de construcción del motor."""
    collection = get_collection()
    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    
    index = VectorStoreIndex.from_vector_store(
        vector_store, storage_context=storage_context
    )
    
    ensemble_retriever = get_ensemble_retriever(index, filtros)
    response_synthesizer = get_response_synthesizer(
        response_mode="compact",
        llm=Settings.llm # Aseguramos inyección directa del LLM Local
    )
    
    query_engine = RetrieverQueryEngine(
        retriever=ensemble_retriever,
        response_synthesizer=response_synthesizer,
        node_postprocessors=[
            ChronicNodePostprocessor()
        ]
    )
    
    # Aplicar el prompt en español
    query_engine.update_prompts({"response_synthesizer:text_qa_template": QA_PROMPT})
    
    return query_engine

def ask_disecan(query: str, filtros: dict | None = None):
    """
    Realiza la búsqueda híbrida y genera la respuesta de forma síncrona.
    Solución al error 'Event loop is closed': no usamos async/await.
    """
    try:
        engine = get_query_engine(filtros)
        
        print(f"[Orchestrator] Procesando consulta: '{query}'...")
        # Usamos query() síncrono en lugar de aquery() asíncrono
        response = engine.query(query)
        
        print(f"[Orchestrator] Recuperados {len(response.source_nodes)} fragmentos.")
        
        sources = []
        for node in response.source_nodes:
            meta = node.metadata
            score = node.score or 0.0
            print(f"  - Fragmento de {meta.get('orador')} (Score: {score:.4f})")
            
            leg = meta.get("legislatura", "")
            pdf_name = meta.get("pdf_file", "")
            pdf_url = (
                f"https://www.parcan.es/publicaciones/diarios/{leg}/{pdf_name}" 
                if pdf_name else "#"
            )

            sources.append({
                "fragment": node.get_content(),
                "speaker": meta.get("orador", "Desconocido"),
                "date": meta.get("fecha", ""),
                "legislature": leg,
                "session": meta.get("num_sesion", ""),
                "pdf_url": pdf_url,
                "score": float(score)
            })
            
        return str(response), sources
    except Exception as e:
        err = str(e)
        print(f"[Orchestrator] ERROR CRÍTICO: {err}")
        if "llama runner process has terminated" in err:
            raise RuntimeError(
                "Ollama ha fallado por falta de recursos. "
                "Cierra otras aplicaciones e inténtalo de nuevo."
            ) from e
        raise e
