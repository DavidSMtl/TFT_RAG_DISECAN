"""
lemmatizer.py — Cliente para el Servicio de Lematización de la ULPGC.

Este módulo se conecta al servicio WCF/SOAP de DiSeCan para obtener lemas exactos.
Incluye una caché local para "respetar" el servidor remoto y evitar peticiones duplicadas.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List

from zeep import Client, Settings as ZeepSettings

# ── Configuración ──────────────────────────────────────────────────────────────

WSDL_URL = "https://appstip.iatext.ulpgc.es/ServicioLematizacionWCF/ServicioLematizacion.svc?wsdl"
CACHE_PATH = Path("assets/lemma_cache.json")

# Tokenizador básico para limpieza previa (mismo que en retriever.py para consistencia)
_STOP_WORDS = {
    "de", "la", "el", "en", "y", "a", "los", "del", "se", "las", "por",
    "un", "una", "con", "que", "es", "para", "al", "lo", "como", "más",
    "o", "pero", "sus", "le", "ya", "han", "no", "si", "cuando", "sobre",
    "esta", "este", "son", "ha", "hay", "fue", "era", "ser", "had", "also",
    "e", "ni", "desde", "hasta", "ante", "bajo", "tras", "sin", "entre",
}

# ── Cliente de Lematización ───────────────────────────────────────────────────

class Lemmatizer:
    def __init__(self):
        self._cache: dict[str, str] = {}
        self._load_cache()
        
        # El cliente zeep se inicializa de forma perezosa (lazy) 
        # para no bloquear si el servidor está caído al arrancar.
        self._client = None
        
    def _load_cache(self):
        if CACHE_PATH.exists():
            try:
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception as e:
                print(f"[Lemmatizer] Error cargando caché: {e}")

    def _save_cache(self):
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Lemmatizer] Error guardando caché: {e}")

    def _init_client(self):
        if self._client is None:
            try:
                # Configurar timeout agresivo (5s) para no bloquear la RAG
                settings = ZeepSettings(strict=False, xml_huge_tree=True)
                self._client = Client(WSDL_URL, settings=settings)
            except Exception as e:
                print(f"[Lemmatizer] ERROR: No se pudo conectar al servicio remoto: {e}")
                return None
        return self._client

    def lemmatize_word(self, word: str) -> str:
        """Obtiene el lema de una sola palabra (usando caché)."""
        w = word.lower().strip()
        if not w:
            return ""
        
        # 1. Consultar caché
        if w in self._cache:
            return self._cache[w]
        
        # 2. Consultar servicio remoto
        client = self._init_client()
        if client:
            try:
                # El servicio DISECAN devuelve una lista de Reconocimientos
                # Tomamos el primero de la lista (el más probable)
                response = client.service.Reconocer(w, "es", False)
                if response:
                    res = response[0]
                    # El lema puede estar en res.FormaCanonica o en res.InfoCanonica.FormaCanonica
                    lema = getattr(res, "FormaCanonica", None)
                    if not lema and hasattr(res, "InfoCanonica"):
                        lema = getattr(res.InfoCanonica, "FormaCanonica", None)
                    
                    lema = lema or w
                    self._cache[w] = lema
                    return lema
            except Exception as e:
                print(f"[Lemmatizer] Fallo remoto para '{w}': {e}")
        
        # 3. Fallback: la misma palabra
        return w

    def lemmatize_query(self, query: str) -> list[str]:
        """Tokeniza y lemmatiza una frase completa, eliminando stop-words."""
        # Limpiar puntuación y dividir
        tokens = re.findall(r"[a-záéíóúüñ]+", query.lower())
        
        lemas = []
        needed_save = False
        
        for t in tokens:
            if t in _STOP_WORDS or len(t) <= 2:
                continue
                
            old_cache_size = len(self._cache)
            lema = self.lemmatize_word(t)
            lemas.append(lema)
            
            if len(self._cache) > old_cache_size:
                needed_save = True
        
        if needed_save:
            self._save_cache()
            
        return list(set(lemas)) # Devolver lemas únicos

# Singleton
_INSTANCE = None

def get_lemas(query: str) -> list[str]:
    """Función de utilidad global (singleton)."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Lemmatizer()
    return _INSTANCE.lemmatize_query(query)

# ── Test Mode ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    # Forzar salida en UTF-8 para evitar problemas de visualización en Windows
    if sys.stdout.encoding.lower() != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    test_query = "¿Cuándo se habló de la universidad y los presupuestos?"
    print(f"Query: {test_query}")
    lemas = get_lemas(test_query)
    print(f"Lemas encontrados: {lemas}")
