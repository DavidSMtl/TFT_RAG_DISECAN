"""
orchestrator.py — Orquestador central de LlamaIndex (Versión Simplificada).
"""
from __future__ import annotations
import logging
import os
from llama_index.core import Settings, VectorStoreIndex, get_response_synthesizer, PromptTemplate
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.schema import QueryBundle
from llama_index.llms.ollama import Ollama
from llama_index.vector_stores.chroma import ChromaVectorStore
from backend.chroma_store import get_collection
from backend.retriever import get_ensemble_retriever
from backend.embedder import embed_query, embed_passages
from backend.query_analyzer import QueryAnalyzer, SearchPlan
from backend.byte_reader import fix_encoding, ByteTextReader
from backend.reranker import LLMReranker

logger = logging.getLogger("disecan.orchestrator")

def setup_settings():
    os.environ["OPENAI_API_KEY"] = "sk-no-key-required"
    Settings.embed_model = type('CustomEmbedder', (BaseEmbedding,), {
        '_get_query_embedding': lambda self, q: embed_query(q, device="cpu"),
        '_get_text_embedding': lambda self, t: embed_passages([t], device="cpu")[0],
        '_get_text_embeddings': lambda self, ts: embed_passages(ts, device="cpu"),
        '_aget_query_embedding': lambda self, q: self._get_query_embedding(q),
        '_aget_text_embedding': lambda self, t: self._get_text_embedding(t)
    })()
    Settings.llm = Ollama(model="qwen2.5:3b", base_url="http://localhost:11434", request_timeout=600.0)

setup_settings()

QA_PROMPT = PromptTemplate(
    "Eres el Asistente Analítico del Parlamento de Canarias, especializado en el Diario de Sesiones.\n"
    "Tu tarea es responder a la pregunta del usuario basándote ESTRICTAMENTE en la información proporcionada en el contexto.\n\n"
    "REGLAS:\n"
    "1. NO inventes información. Si el contexto no contiene la respuesta o no está relacionado con la pregunta, di: 'No he encontrado información específica sobre [tema] en los fragmentos recuperados del Diario de Sesiones.'\n"
    "2. Usa un tono institucional, claro y directo.\n"
    "3. Cita a los oradores o intervinientes si aparecen en el contexto.\n"
    "4. Estructura la respuesta usando viñetas o párrafos cortos para facilitar la lectura.\n\n"
    "--- CONTEXTO ---\n"
    "{context_str}\n\n"
    "--- PREGUNTA ---\n"
    "{query_str}\n\n"
    "Respuesta Analítica:"
)

_ANALYZER = QueryAnalyzer()
_RERANKER = LLMReranker()

def get_query_engine(plan: SearchPlan, filtros: dict | None = None):
    """Inicializa el motor de consulta con el retriever híbrido configurado por el plan."""
    collection = get_collection()
    index = VectorStoreIndex.from_vector_store(ChromaVectorStore(chroma_collection=collection))
    retriever = get_ensemble_retriever(index, plan, filtros)
    
    query_engine = RetrieverQueryEngine(
        retriever=retriever,
        response_synthesizer=get_response_synthesizer(response_mode="compact")
    )
    query_engine.update_prompts({"response_synthesizer:text_qa_template": QA_PROMPT})
    return query_engine


def ask_disecan(query: str, filtros: dict | None = None, mode: str = "full"):
    """Pipeline RAG completo simplificado."""
    
    # 1. Analizar Query
    plan = _ANALYZER.analyze(query)
    
    query_bundle = QueryBundle(
        query_str=query,
        custom_embedding_strs=[plan.hypothetical_answer] if (mode == "full" and plan.hypothetical_answer) else None
    )

    # 2. Recuperación Híbrida
    collection = get_collection()
    index = VectorStoreIndex.from_vector_store(ChromaVectorStore(chroma_collection=collection))
    retriever = get_ensemble_retriever(index, plan, filtros, mode=mode)

    initial_nodes = retriever.retrieve(query_bundle)
    
    # 3. Re-ranking
    if mode == "linguistics_only":
        reranked_nodes = initial_nodes[:10]
    else:
        reranked_nodes = _RERANKER.rerank(query, initial_nodes)

    # 4. Síntesis
    if mode == "linguistics_only":
        num_coincidencias = len(initial_nodes)
        response_text = (
            f"Búsqueda lingüística finalizada. Se han encontrado {num_coincidencias} coincidencia(s)."
            if num_coincidencias > 0 
            else "No se han encontrado coincidencias."
        )
        response = type("ProgrammaticResponse", (object,), {"response": response_text, "__str__": lambda self: response_text})()
    else:
        synthesizer = get_response_synthesizer(response_mode="compact")
        synthesizer.update_prompts({"text_qa_template": QA_PROMPT})
        response = synthesizer.synthesize(query_bundle, nodes=reranked_nodes)
    
    keywords = list(set(plan.semantic_concepts + plan.literal_terms + plan.sequential_phrases))

    # 5. Formatear Fuentes (leyendo de los ficheros físicos vía offsets)
    _reader = ByteTextReader()
    sources = []
    for node in reranked_nodes:
        meta = node.metadata
        
        # Leer Frase (Corto)
        b_frase_start = int(meta.get("b_frase_start", 0))
        b_frase_len   = int(meta.get("b_frase_len", 0))
        res = _reader.get_sentence_and_paragraph_offsets(b_frase_start, b_frase_len)
        sentence = res["sentence"] if res["sentence"] else node.get_content().strip()

        # Leer Párrafo (Contexto ampliado)
        b_par_start = int(meta.get("b_par_start", 0))
        b_par_len   = int(meta.get("b_par_len",   0))
        paragraph   = _reader.get_paragraph(b_par_start, b_par_len) if b_par_len > 0 else ""

        sources.append({
            "fragment":   sentence,
            "context":    paragraph,
            "speaker":    fix_encoding(meta.get("orador", "Desconocido")),
            "date":       meta.get("fecha", ""),
            "legislature": meta.get("legislatura", ""),
            "score":      round(float(node.score or 0.0) * 100, 1),
            "id":         node.id_
        })

    # Asegurarnos de que las palabras originales de la búsqueda también se incluyan para resaltarse
    # Quitamos puntuación básica y stopwords
    import re
    raw_words = [w for w in re.split(r'\W+', query.lower()) if len(w) > 3]
    for w in raw_words:
        if w not in keywords:
            keywords.append(w)

    return str(response), sources, keywords
