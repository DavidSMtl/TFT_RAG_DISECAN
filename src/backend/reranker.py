import re
import json
from typing import List
from llama_index.core.schema import NodeWithScore
from llama_index.llms.ollama import Ollama

class LLMReranker:
    def __init__(self, model_name: str = "qwen2.5:3b", base_url: str = "http://localhost:11434"):
        self.llm = Ollama(model=model_name, base_url=base_url, request_timeout=60.0)

    def rerank(self, query: str, nodes: List[NodeWithScore], top_n: int = 10) -> List[NodeWithScore]:
        if not nodes:
            return []
            
        # Solo re-rankeamos los top_k iniciales para no matar latencia (max 15)
        candidates = nodes[:15]
        
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
        try:
            response = self.llm.complete(prompt)
            # Extraer la lista [ ... ] usando regex
            match = re.search(r'\[(\d+,\s*)*\d+\]', str(response))
            if match:
                indices = json.loads(match.group(0))
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
                return reranked[:top_n]
        except Exception as e:
            print(f"Error en re-rankeo: {e}")
            return nodes[:top_n]
            
        return nodes[:top_n]
