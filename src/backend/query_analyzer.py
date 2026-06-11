import json
import logging
import re
from typing import List
from llama_index.llms.ollama import Ollama
from pydantic import BaseModel, Field

logger = logging.getLogger("disecan.analyzer")

class SearchPlan(BaseModel):
    semantic_concepts: List[str] = Field(default_factory=list, description="Conceptos para expansión y búsqueda semántica (lemas)")
    literal_terms: List[str] = Field(default_factory=list, description="Términos que deben buscarse exactos (sin lematizar)")
    sequential_phrases: List[str] = Field(default_factory=list, description="Secuencias exactas protegidas (ej: Proposición no de ley)")
    entities: List[str] = Field(default_factory=list, description="Nombres propios, leyes, lugares")
    hypothetical_answer: str = Field(default="", description="Párrafo HyDE: para búsqueda semántica")
    intent: str = Field(default="hybrid", description="exact, semantic, hybrid")

class QueryAnalyzer:
    def __init__(self, model_name: str = "qwen2.5:3b", base_url: str = "http://localhost:11434"):
        self.llm = Ollama(model=model_name, base_url=base_url, request_timeout=30.0)
        
    def analyze(self, query: str) -> SearchPlan:
        logger.debug(f"[Analyzer] ▶ Analizando Query: '{query}'")

        # Bypaseo si tiene sintaxis especial de DiSeCan
        if any(c in query for c in "[]<>*") or ":" in query:
            logger.info("[Analyzer] Sintaxis especial detectada. Bypaseando LLM.")
            return SearchPlan(sequential_phrases=[query.strip()], intent="exact")

        manual_quotes = re.findall(r'"([^"]*)"', query)
        
        prompt = f"""
Eres un experto en Recuperación de Información y Lingüística (RAG) trabajando para el Parlamento de Canarias.
Tu objetivo es analizar una consulta de usuario y extraer sus componentes para alimentar un motor de búsqueda híbrido (Semántico + SQL Lexicográfico).

INSTRUCCIONES ESTRICTAS:
1. Devuelve ÚNICAMENTE un objeto JSON válido. No añadas texto antes ni después.
2. Analiza los componentes siguiendo esta estructura:
   - "semantic_concepts": Lista de conceptos temáticos de la consulta y al menos 2 sinónimos o palabras relacionadas para expandir la búsqueda. (Ej: Si busca "sanidad", añade "hospitales", "salud", "médicos").
   - "literal_terms": Palabras clave muy específicas que deben buscarse exactas (adjetivos clave, verbos concretos).
   - "sequential_phrases": Frases hechas o conceptos compuestos donde el orden de las palabras no debe romperse.
   - "entities": Entidades nombradas como instituciones, leyes, islas, municipios o personas.
   - "hypothetical_answer": Un párrafo de 2 líneas simulando una respuesta hipotética ideal a la pregunta (para usar técnica HyDE).
   - "intent": Siempre usa "hybrid".

EJEMPLO 1:
Consulta: "¿Qué se dijo sobre la cesta de la compra y su encarecimiento?"
{{
  "semantic_concepts": ["cesta de la compra", "inflación", "precios", "coste de vida", "economía"],
  "literal_terms": ["encarecimiento"],
  "sequential_phrases": ["cesta de la compra"],
  "entities": [],
  "hypothetical_answer": "El encarecimiento de la cesta de la compra es un problema grave. Se propone reducir el IGIC a los productos básicos para aliviar la inflación.",
  "intent": "hybrid"
}}

EJEMPLO 2:
Consulta: "Buscar sobre la Universidad de Las Palmas de Gran Canaria"
{{
  "semantic_concepts": ["educación superior", "universidad", "formación universitaria", "instituciones académicas"],
  "literal_terms": [],
  "sequential_phrases": ["Universidad de Las Palmas de Gran Canaria", "ULPGC"],
  "entities": ["Universidad de Las Palmas de Gran Canaria", "Gran Canaria", "Las Palmas"],
  "hypothetical_answer": "La Universidad de Las Palmas de Gran Canaria (ULPGC) es un referente en la educación superior del archipiélago. Ha recibido nuevas inversiones para mejorar sus facultades.",
  "intent": "hybrid"
}}

Consulta Actual: "{query}"
Respuesta JSON:
"""
        try:
            response = self.llm.complete(prompt)
            raw_text = response.text.strip()
            data = json.loads(raw_text)
            
            # Asegurar que todos los campos de lista sean strings, ya que el LLM a veces devuelve diccionarios
            for field in ["semantic_concepts", "literal_terms", "sequential_phrases", "entities"]:
                raw_list = data.get(field, [])
                if not isinstance(raw_list, list):
                    raw_list = [raw_list]
                cleaned_list = []
                for item in raw_list:
                    if isinstance(item, dict):
                        # Extraer el primer valor del diccionario o usar str()
                        vals = list(item.values())
                        cleaned_list.append(str(vals[0]) if vals else str(item))
                    else:
                        cleaned_list.append(str(item))
                data[field] = cleaned_list

            if manual_quotes:
                data.setdefault("literal_terms", []).extend(manual_quotes)
                data["literal_terms"] = list(set(data["literal_terms"]))
            
            plan = SearchPlan(**data)
            logger.info(f"[Analyzer] ✔ Plan generado: concepts={plan.semantic_concepts}")
            return plan
            
        except Exception as e:
            logger.error(f"[Analyzer] Fallo en LLM ({e}). Usando fallback léxico.")
            return SearchPlan(semantic_concepts=query.split())
