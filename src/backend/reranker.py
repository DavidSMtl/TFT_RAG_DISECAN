import logging
import re
import json
from typing import List
from llama_index.core.schema import NodeWithScore
from llama_index.llms.ollama import Ollama

# ── Logger ────────────────────────────────────────────────────────────────────
logger = logging.getLogger("disecan.reranker")

class LLMReranker:
    def __init__(self, model_name: str = "qwen2.5:3b", base_url: str = "http://localhost:11434"):
        self.llm = Ollama(model=model_name, base_url=base_url, request_timeout=60.0)

    def rerank(self, query: str, nodes: List[NodeWithScore], top_n: int = 10) -> List[NodeWithScore]:
        if not nodes:
            logger.warning("[Reranker] ✗ Lista de nodos vacía — nada que re-rankear.")
            return []
            
        # Solo re-rankeamos los top_k iniciales para no matar latencia (max 15)
        candidates = nodes[:15]

        logger.info(f"[Reranker] ── RE-RANKING ({'─' * 30})")
        logger.info(f"[Reranker]   Total nodos recibidos: {len(nodes)} | Candidatos evaluados: {len(candidates)}")
        logger.debug(f"[Reranker]   Candidatos (id, score_previo, orador):")
        for i, n in enumerate(candidates):
            meta = n.node.metadata
            preview = n.node.get_content().replace("\n", " ")[:80]
            logger.debug(
                f"[Reranker]     [{i:2d}] score={round(float(n.score or 0), 4):.4f} | "
                f"orador='{meta.get('orador', '?')}' | texto='{preview}...'"
            )
        
        context_str = ""
        for i, node in enumerate(candidates):
            text = node.node.get_content().replace("\n", " ")[:300]
            context_str += f"[{i}] {text}\n\n"

        prompt = f"""
Evalúa la relevancia de los siguientes fragmentos para responder a la consulta: "{query}".

CRITERIOS DE RELEVANCIA:
1. **Prioridad Máxima**: Fragmentos que contengan frases exactas o términos técnicos mencionados (ej: "Proposición no de ley").
2. **Relevancia Semántica**: Fragmentos que expliquen razones, causas o consecuencias del tema consultado.
3. **Calidad del Orador**: Declaraciones directas de diputados son más valiosas que menciones administrativas.

Devuelve exclusivamente una lista de índices [id] ordenados de MAYOR a MENOR relevancia.
Formato: [indice, indice, ...]

FRAGMENTOS A EVALUAR:
{context_str}

ORDEN DE RELEVANCIA (SOLO LA LISTA JSON):
"""
        logger.debug(f"[Reranker] ── PROMPT ENVIADO AL LLM ({'─' * 20})")
        logger.debug(prompt)
        logger.debug(f"[Reranker] {'─' * 50}")

        try:
            response = self.llm.complete(prompt)
            raw_response = str(response).strip()
            logger.debug(f"[Reranker] ── RESPUESTA RAW DEL LLM ({'─' * 18})")
            logger.debug(raw_response)
            logger.debug(f"[Reranker] {'─' * 50}")

            # Extraer la lista [ ... ] usando regex
            match = re.search(r'\[(\d+,\s*)*\d+\]', raw_response)
            if match:
                indices = json.loads(match.group(0))
                logger.debug(f"[Reranker]   Índices extraídos del LLM: {indices}")

                # Re-ordenar
                reranked = []
                seen = set()
                for idx in indices:
                    if idx < len(candidates) and idx not in seen:
                        reranked.append(candidates[idx])
                        seen.add(idx)
                
                # Añadir los que falten por si el LLM olvidó alguno
                for i, node in enumerate(candidates):
                    if i not in seen:
                        reranked.append(node)
                
                # Añadir el resto que no entró en el re-rankeo top 15
                reranked.extend(nodes[15:])
                final = reranked[:top_n]

                logger.debug(f"[Reranker]   Orden FINAL (primeros {len(final)}):")
                for rank, n in enumerate(final):
                    meta = n.node.metadata
                    logger.debug(
                        f"[Reranker]     #{rank + 1:2d} — id={n.node.id_} | "
                        f"orador='{meta.get('orador', '?')}' | fecha='{meta.get('fecha', '?')}'"
                    )
                logger.debug(f"[Reranker] {'─' * 50}")
                return final
            else:
                logger.warning("[Reranker]   ✗ No se pudo extraer lista de índices del LLM. Usando orden original.")
        except Exception as e:
            logger.error(f"[Reranker]   ✗ Error en re-rankeo: {e}. Devolviendo orden original.")
            return nodes[:top_n]
            
        return nodes[:top_n]
