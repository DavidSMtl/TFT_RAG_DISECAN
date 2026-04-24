import json
import re
from typing import List, Dict, Any, Optional
from llama_index.llms.ollama import Ollama
from pydantic import BaseModel, Field

class SearchPlan(BaseModel):
    semantic_concepts: List[str] = Field(default_factory=list, description="Conceptos para expansión y búsqueda semántica (lemas)")
    literal_terms: List[str] = Field(default_factory=list, description="Términos que deben buscarse exactos (sin lematizar)")
    sequential_phrases: List[str] = Field(default_factory=list, description="Secuencias exactas protegidas (ej: Proposición no de ley)")
    entities: List[str] = Field(default_factory=list, description="Nombres propios, leyes, lugares")
    hypothetical_answer: str = Field(default="", description="Párrafo HyDE: para búsqueda semántica")
    intent: str = Field(default="hybrid", description="exact, semantic, hybrid")
    must_have: List[str] = Field(default_factory=list) # Por compatibilidad
    expansion: List[str] = Field(default_factory=list) # Por compatibilidad
    exact_phrases: List[str] = Field(default_factory=list) # Por compatibilidad

class QueryAnalyzer:
    def __init__(self, model_name: str = "qwen2.5:3b", base_url: str = "http://localhost:11434"):
        self.llm = Ollama(model=model_name, base_url=base_url, request_timeout=30.0)
        
    def analyze(self, query: str) -> SearchPlan:
        # Regex para detectar comillas manuales (se tratan como literales)
        print(f"\n[Analyzer] Analizando consulta: '{query}'")
        manual_quotes = re.findall(r'"([^"]*)"', query)
        
        prompt = f"""
Eres un Analista Lexicográfico y Experto en Debates del Parlamento de Canarias. Tu misión es transformar una consulta en lenguaje natural en un 'SearchPlan' técnico altamente preciso para un sistema RAG.

REGLAS DE CATEGORIZACIÓN:
1. 'sequential_phrases': Úsalo para N-gramas donde el orden y las palabras vacías (de, la, no, el) son CRÍTICOS para el significado legal. 
   - Ej: "Proposición no de ley", "Comisión de Sanidad", "Diario de Sesiones".
2. 'literal_terms': Palabras que NO deben lematizarse. El usuario busca la forma morfológica exacta.
   - Ej: "encarecimiento" (no buscar 'caro'), "subvencionadas" (específico femenino plural).
3. 'semantic_concepts': Conceptos generales. DEBES realizar EXPANSIÓN LÉXICA (sinónimos/temas relacionados) para alimentar al buscador.
   - Ej: si busca "cesta de la compra", expande a ["inflación", "precios", "coste de vida"].
4. 'entities': Nombres de diputados, instituciones o leyes específicas (ej: "Casimiro Curbelo", "Copecan", "Ley del Suelo").
5. 'hypothetical_answer': Escribe un párrafo breve (2 frases) que simule una respuesta ideal. Esto mejora la recuperación semántica (técnica HyDE).

EJEMPLOS:
Consulta: "¿Por qué está tan cara la cesta de la compra?"
Respuesta: {{
  "semantic_concepts": ["cesta de la compra", "inflación", "precios", "coste de vida", "economía doméstica"],
  "literal_terms": ["cara"],
  "sequential_phrases": [],
  "entities": [],
  "hypothetical_answer": "El encarecimiento de la cesta de la compra se debe al aumento de la inflación y los costes de transporte en Canarias.",
  "intent": "hybrid"
}}

Consulta Actual: "{query}"
Respuesta (solo JSON):
"""
        try:
            response = self.llm.complete(prompt)
            data = json.loads(response.text)
            
            # Sanatizar entidades para asegurar que son strings (el LLM a veces devuelve dicts)
            raw_entities = data.get("entities", [])
            data["entities"] = [
                e["name"] if isinstance(e, dict) and "name" in e else str(e) 
                for e in raw_entities
            ]

            # Retrocompatibilidad y limpieza
            data["must_have"] = data.get("semantic_concepts", [])
            data["expansion"] = data.get("literal_terms", [])
            data["exact_phrases"] = data.get("sequential_phrases", [])
            
            if manual_quotes:
                data.setdefault("literal_terms", []).extend(manual_quotes)
                data["literal_terms"] = list(set(data["literal_terms"]))
            
            plan = SearchPlan(**data)
            print(f"[Analyzer] HyDE: {plan.hypothetical_answer[:60]}...")
            print(f"[Analyzer] Términos clave: {plan.semantic_concepts + plan.literal_terms}")
            return plan
        except Exception as e:
            print(f"[Analyzer] Error: {e}. Usando fallback.")
            return SearchPlan(semantic_concepts=query.split())

if __name__ == "__main__":
    analyzer = QueryAnalyzer()
    plan = analyzer.analyze('¿Qué ha dicho Casimiro Curbelo sobre el "sistema de salud" canario?')
    print(plan.model_dump_json(indent=2))
