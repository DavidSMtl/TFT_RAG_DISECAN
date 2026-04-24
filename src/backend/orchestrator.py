"""
orchestrator.py — Orquestador central de LlamaIndex (Versión Simplificada).
"""
from __future__ import annotations
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
from backend.byte_reader import fix_encoding
from backend.reranker import LLMReranker

# KEEP STOPWORDS as requested by the user for future advanced features
STOPWORDS = {
    "que", "de", "se", "el", "la", "a", "en", "y", "o", "un", "una", 
    "los", "las", "por", "con", "no", "su", "sus", "para", "como", 
    "al", "lo", "del", "qué", "cuál", "cuáles", "quién", "quiénes",
    "donde", "cuando", "esta", "este", "estos", "estas", "han", "ha", 
    "hay", "es", "son", "fue", "eran"
}

import torch

def setup_settings():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[Orchestrator] Configurando LlamaIndex en dispositivo: {device}")
    
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

def ask_disecan(query: str, filtros: dict | None = None):
    # 1. Analizar la consulta (Agentic part: HyDE, Expansion, Literals)
    plan = _ANALYZER.analyze(query)
    print(f"[Orchestrator] Plan de búsqueda: {plan.intent} | Conceptos: {plan.semantic_concepts}")

    # 3. Recuperación Híbrida Manual para poder aplicar Re-ranking
    query_bundle = QueryBundle(
        query_str=query,
        custom_embedding_strs=[plan.hypothetical_answer] if plan.hypothetical_answer else None
    )
    
    collection = get_collection()
    index = VectorStoreIndex.from_vector_store(ChromaVectorStore(chroma_collection=collection))
    retriever = get_ensemble_retriever(index, plan, filtros)
    
    initial_nodes = retriever.retrieve(query_bundle)
    
    # 4. Re-ranking con LLM (Ollama)
    print(f"[Orchestrator] Aplicando re-ranking a {len(initial_nodes)} candidatos...")
    reranked_nodes = _RERANKER.rerank(query, initial_nodes)
    
    # 5. Síntesis de respuesta
    synthesizer = get_response_synthesizer(response_mode="compact")
    synthesizer.update_prompts({"text_qa_template": QA_PROMPT})
    
    response = synthesizer.synthesize(query_bundle, nodes=reranked_nodes)
    
    sources = []
    for node in reranked_nodes:
        meta = node.metadata
        sources.append({
            "fragment": node.get_content(),
            "speaker": fix_encoding(meta.get("orador", "Desconocido")),
            "date": meta.get("fecha", ""),
            "legislature": meta.get("legislatura", ""),
            "score": round(float(node.score or 0.0) * 100, 1),
            "id": node.id_
        })
    
    # Devolvemos los términos usados para que el usuario pueda evaluarlos
    keywords = plan.semantic_concepts + plan.literal_terms + plan.sequential_phrases
    print(f"[Orchestrator] Respuesta generada con {len(sources)} fuentes.")
    return str(response), sources, list(set(keywords))
