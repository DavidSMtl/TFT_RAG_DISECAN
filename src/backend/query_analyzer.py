import json
import re
from typing import List, Dict, Any, Optional
from llama_index.llms.ollama import Ollama
from pydantic import BaseModel, Field

class SearchPlan(BaseModel):
    must_have: List[str] = Field(default_factory=list, description="Palabras clave obligatorias (sustantivos/verbos)")
    exact_phrases: List[str] = Field(default_factory=list, description="Frases entre comillas o secuencias literales")
    entities: List[str] = Field(default_factory=list, description="Nombres propios, leyes, lugares")
    expansion: List[str] = Field(default_factory=list, description="Diccionario de intenciones: sinónimos y términos técnicos relacionados")
    hypothetical_answer: str = Field(default="", description="Párrafo HyDE: cómo sonaría la respuesta ideal (2-3 líneas)")
    intent: str = Field(default="hybrid", description="Tipo de búsqueda: exact, semantic, hybrid")

class QueryAnalyzer:
    def __init__(self, model_name: str = "qwen2.5:3b", base_url: str = "http://localhost:11434"):
        self.llm = Ollama(model=model_name, base_url=base_url, request_timeout=30.0)
        
    def analyze(self, query: str) -> SearchPlan:
        # Extracción rápida de comillas por regex
        manual_quotes = re.findall(r'"([^"]*)"', query)
        
        prompt = f"""
Eres un Arquitecto de Búsqueda experto en debates parlamentarios. Tu tarea es descomponer la consulta en un plan de búsqueda estructurado (JSON).

OBJETIVO:
1. Generar un 'DICCIONARIO DE INTENCIONES': Si el usuario usa palabras comunes, genera términos técnicos parlamentarios (sinónimos expertos).
2. Generar un 'PÁRRAFO HyDE': Escribe 2 líneas de cómo sonaría la respuesta ideal del diputado. Esto ayuda a la búsqueda semántica.

REGLAS JSON:
- 'must_have': Lemas principales.
- 'expansion': Sinónimos técnicos (ej: "cesta compra" -> ["carestía", "inflación", "flete"]).
- 'hypothetical_answer': Una mini-respuesta inventada que contenga la información buscada.
- 'entities': Nombres propios.

EJEMPLO:
Consulta: "¿Por qué está tan cara la cesta de la compra?"
Respuesta: {{
  "must_have": ["cesta", "compra", "caro"],
  "expansion": ["carestía", "inflación", "precios", "suministros", "flete"],
  "hypothetical_answer": "La carestía de la cesta de la compra y el incremento de los precios se debe al monopolio de los fletes marítimos y los costes de importación en las islas.",
  "entities": [],
  "exact_phrases": [],
  "intent": "hybrid"
}}

Consulta Actual: "{query}"
Respuesta (solo JSON):
"""
        try:
            response = self.llm.complete(prompt)
            # Limpiar posibles bloques de código markdown
            clean_res = re.sub(r'```json|```', '', str(response)).strip()
            data = json.loads(clean_res)
            
            # Mezclar con las comillas detectadas manualmente por seguridad
            if manual_quotes:
                data.setdefault("exact_phrases", []).extend(manual_quotes)
                data["exact_phrases"] = list(set(data["exact_phrases"]))
                
            return SearchPlan(**data)
        except Exception as e:
            print(f"Error analizando query: {e}")
            # Fallback seguro
            return SearchPlan(
                must_have=query.split(),
                intent="hybrid"
            )

if __name__ == "__main__":
    analyzer = QueryAnalyzer()
    plan = analyzer.analyze('¿Qué ha dicho Casimiro Curbelo sobre el "sistema de salud" canario?')
    print(plan.model_dump_json(indent=2))
