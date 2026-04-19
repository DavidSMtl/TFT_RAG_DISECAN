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
        manual_quotes = re.findall(r'"([^"]*)"', query)
        
        prompt = f"""
Eres un Arquitecto de Búsqueda experto en debates parlamentarios. Tu tarea es descomponer la consulta en un plan de búsqueda estructurado (JSON).

IMPORTANTE - CATEGORÍAS DE BÚSQUEDA:
1. 'sequential_phrases': Bloques donde el orden y las palabras vacías Importan (ej: "Proposición no de ley", "Comisión de Economía"). NO ELIMINES "no", "de", "la".
2. 'literal_terms': Palabras que el usuario quiere exactas, sin lematizar (ej: si busca "subvencionadas", no buscar "subvención").
3. 'semantic_concepts': Ideas generales para expandir con sinónimos.

EJEMPLO:
Consulta: "Dime qué se aprobó sobre la tasa turística en una proposición no de ley."
Respuesta: {{
  "semantic_concepts": ["aprobación", "impuestos", "turismo"],
  "literal_terms": ["tasa turística"],
  "sequential_phrases": ["proposición no de ley"],
  "entities": [],
  "hypothetical_answer": "Se ha debatido y aprobado la implementación de una tasa turística mediante una proposición no de ley para regular el impacto del sector.",
  "intent": "hybrid"
}}

Consulta Actual: "{query}"
Respuesta (solo JSON):
"""
        try:
            response = self.llm.complete(prompt)
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
                
            return SearchPlan(**data)
        except Exception as e:
            print(f"Error analizando query: {e}")
            return SearchPlan(semantic_concepts=query.split())
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
