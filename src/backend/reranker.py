import logging
from typing import List
from llama_index.core.schema import NodeWithScore
from sentence_transformers import CrossEncoder

# ── Logger ────────────────────────────────────────────────────────────────────
logger = logging.getLogger("disecan.reranker")

class LLMReranker:
    """Mantenemos el nombre de la clase para no romper orchestrator.py, pero ahora usa un CrossEncoder."""
    def __init__(self, model_name: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"):
        logger.info(f"[Reranker] Cargando modelo CrossEncoder '{model_name}' en CPU...")
        # Forzamos dispositivo CPU para no colapsar la VRAM de la gráfica y dejarla para Ollama
        self.model = CrossEncoder(model_name, max_length=512, device="cpu")

    def rerank(self, query: str, nodes: List[NodeWithScore], top_n: int = 10) -> List[NodeWithScore]:
        if not nodes:
            return []
            
        logger.info(f"[Reranker] Evaluando {len(nodes)} nodos con CrossEncoder...")
        
        # 1. Preparar pares de (pregunta, texto_del_documento)
        pairs = [[query, n.node.get_content()] for n in nodes]
        
        # 2. El CrossEncoder puntúa todos los pares instantáneamente
        scores = self.model.predict(pairs)
        
        import math
        
        # 3. Asignamos los nuevos scores de relevancia a los nodos (normalizados con sigmoide)
        for i, node in enumerate(nodes):
            # El CrossEncoder devuelve logits crudos (ej: -3.5 a 4.2)
            # Usamos una función sigmoide para aplastarlos a un rango [0.0, 1.0]
            raw_score = float(scores[i])
            normalized_score = 1.0 / (1.0 + math.exp(-raw_score))
            node.score = normalized_score
            
        # 4. Ordenamos de mayor a menor puntuación y devolvemos el top_N
        reranked = sorted(nodes, key=lambda x: x.score, reverse=True)
        
        logger.debug(f"[Reranker] Top 3 scores normalizados: {[round(n.score, 4) for n in reranked[:3]]}")
        return reranked[:top_n]
