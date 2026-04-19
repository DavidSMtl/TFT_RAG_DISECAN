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
from backend.query_analyzer import QueryAnalyzer
from backend.reranker import LLMReranker

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

import json
import re

# Lista básica de stopwords en español para filtrado de relevancia
STOPWORDS = {
    "que", "de", "se", "el", "la", "a", "en", "y", "o", "un", "una", 
    "los", "las", "por", "con", "no", "su", "sus", "para", "como", 
    "al", "lo", "del", "qué", "cuál", "cuáles", "quién", "quiénes",
    "donde", "cuando", "esta", "este", "estos", "estas", "han", "ha", 
    "hay", "es", "son", "fue", "eran"
}

def get_sentence_score(sentence: str, query_words: set[str]) -> float:
    """
    Calcula una puntuación de solapamiento de palabras con pesos diferenciados:
    - Palabras de contenido (no stopwords): 10.0 puntos
    - Palabras comunes (stopwords): 1.0 puntos
    - Coincidencia parcial (ej: plurales): 5.0 puntos
    """
    if not sentence or not query_words:
        return 0.0
        
    s_text = sentence.lower()
    s_words = set(re.findall(r"\w+", s_text))
    score = 0.0
    
    for qw in query_words:
        # 1. Coincidencia exacta
        if qw in s_words:
            if qw in STOPWORDS:
                score += 1.0
            else:
                score += 10.0
        # 2. Coincidencia parcial (manejo de plurales/raíces)
        else:
            # Solo si la palabra es suficientemente larga para no dar falsos positivos
            if len(qw) > 3:
                for sw in s_words:
                    if len(sw) > 3 and (qw in sw or sw in qw):
                        # Evitamos dar puntos a stopwords que coincidan parcialmente
                        if qw not in STOPWORDS and sw not in STOPWORDS:
                            score += 5.0
                            break # Solo un match parcial por palabra de query
    return score

class SentencePickerPostprocessor(BaseNodePostprocessor):
    """
    Selecciona la frase más relevante dentro de un chunk (Párrafo) 
    basándose en la query del usuario.
    """
    def _postprocess_nodes(
        self, nodes: list[NodeWithScore], query_bundle: QueryBundle | None = None
    ) -> list[NodeWithScore]:
        if not query_bundle:
            return nodes
            
        query_text = query_bundle.query_str.lower()
        query_words = set(re.findall(r"\w+", query_text))
        
        for nws in nodes:
            meta = nws.node.metadata
            frases_json = meta.get("frases_data")
            
            if frases_json:
                try:
                    frases_map = json.loads(frases_json)
                    best_text = ""
                    max_score = -1.0
                    
                    # Buscamos la frase con más palabras coincidentes
                    for fid, text in frases_map.items():
                        score = get_sentence_score(text, query_words)
                        if score > max_score:
                            max_score = score
                            best_text = text
                    
                    if best_text:
                        nws.node.metadata["original_sentence"] = best_text
                except Exception as e:
                    print(f"[Orchestrator] Error decodificando frases_data: {e}")
            
            # Fallback si no hay mapa o falla la selección
            if "original_sentence" not in nws.node.metadata:
                nws.node.metadata["original_sentence"] = nws.node.get_content()
        
        return nodes

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
    "Eres un asistente analítico especializado en el Parlamento de Canarias.\n"
    "Se te proporcionan fragmentos de intervenciones parlamentarias (párrafos).\n"
    "Tu objetivo es generar un RESUMEN completo y estructurado de la información hallada.\n"
    "---------------------\n"
    "{context_str}\n"
    "---------------------\n"
    "Pregunta del usuario: {query_str}\n\n"
    "Instrucciones estricatmente obligatorias:\n"
    "1. Responde SIEMPRE en ESPAÑOL.\n"
    "2. Sintetiza la información en párrafos breves y claros.\n"
    "3. Si hay varios oradores, agrupa lo que dicen de forma coherente.\n"
    "4. Cita nombres y fechas si son relevantes.\n"
    "5. Si no hay información suficiente en los fragmentos, di: 'No se ha encontrado información específica en el diario de sesiones.'\n"
    "6. NO divagues. Ve directo al grano.\n\n"
    "7. No inventes información que no esté en los fragmentos.\n\n"
    "Resumen:"
)
QA_PROMPT = PromptTemplate(QA_PROMPT_STR)

# ── Singleton para el motor RAG ─────────────────────────────────────────────

_QUERY_ENGINE = None
query_analyzer = QueryAnalyzer()
reranker = LLMReranker()

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
            SentencePickerPostprocessor(),
            ChronicNodePostprocessor()
        ]
    )
    
    # Aplicar el prompt en español
    query_engine.update_prompts({"response_synthesizer:text_qa_template": QA_PROMPT})
    
    return query_engine

def ask_disecan(query: str, filtros: dict | None = None):
    """
    Realiza la búsqueda híbrida y genera la respuesta de forma síncrona.
    Integrando el Analizador de Consultas y el Re-rankeo LLM.
    """
    try:
        # 1. Análisis Agéntico
        print(f"[Orchestrator] Analizando consulta: '{query}'...")
        plan = query_analyzer.analyze(query)
        
        # 2. Preparación de Búsqueda
        # Pasamos el plan como JSON en el query_str para el retriever léxico
        # Pero usamos el Párrafo HyDE para el embedding vectorial
        plan_json = plan.model_dump_json()
        
        hyde_text = plan.hypothetical_answer if plan.hypothetical_answer else query
        print(f"[Orchestrator] HyDE (Párrafo Hipotético): {hyde_text[:100]}...")
        
        bundle = QueryBundle(
            query_str=plan_json, 
            embedding=Settings.embed_model.get_query_embedding(hyde_text) # Consistencia CPU
        )
        
        engine = get_query_engine(filtros)
        
        # 3. Recuperación Inicial
        print(f"[Orchestrator] Ejecutando búsqueda híbrida...")
        initial_response = engine.query(bundle)
        
        # 4. Re-rankeo Contextual (Refinamiento)
        print(f"[Orchestrator] Re-rankeando {len(initial_response.source_nodes)} fragmentos filtrados...")
        final_nodes = reranker.rerank(query, initial_response.source_nodes, top_n=5)
        
        # 5. Síntesis Final (usando los nodos refinados)
        # Re-creamos el sintetizador o simplemente usamos el del engine
        # pero para asegurar que use SOLO los re-rankeados, sintetizamos manualmente
        response_synthesizer = get_response_synthesizer(
            response_mode="compact",
            llm=Settings.llm
        )
        # Actualizar prompt del sintetizador manual
        response_synthesizer.update_prompts({"text_qa_template": QA_PROMPT})
        
        final_response = response_synthesizer.synthesize(
            query=query,
            nodes=final_nodes
        )
        
        sources = []
        for node in final_nodes:
            meta = node.metadata
            score = node.score or 0.0
            
            leg = meta.get("legislatura", "")
            pdf_name = meta.get("pdf_file", "")
            pdf_url = (
                f"https://www.parcan.es/publicaciones/diarios/{leg}/{pdf_name}" 
                if pdf_name else "#"
            )

            sources.append({
                "fragment": meta.get("original_sentence", node.get_content()),
                "context": node.get_content(),
                "speaker": meta.get("orador", "Desconocido"),
                "date": meta.get("fecha", ""),
                "legislature": leg,
                "session": meta.get("num_sesion", ""),
                "pdf_url": pdf_url,
                "score": float(score)
            })
            
        # Keywords para resaltado en frontend (incluyendo expansión léxica/sinónimos)
        keywords = list(set(plan.must_have + plan.entities + plan.expansion + plan.exact_phrases))
        
        return str(final_response), sources, keywords
    except Exception as e:
        err = str(e)
        print(f"[Orchestrator] ERROR CRÍTICO: {err}")
        if "llama runner process has terminated" in err:
            raise RuntimeError(
                "Ollama ha fallado por falta de recursos. "
                "Cierra otras aplicaciones e inténtalo de nuevo."
            ) from e
        raise e
