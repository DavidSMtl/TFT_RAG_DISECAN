"""
API REST encargada de comunicar el RAG con el frontend.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ── Logging global ─────────────────────────────────────────────────────────────
# Siempre activo a nivel INFO. Los módulos del pipeline usan el nivel INFO/ERROR.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Silenciar librerías ruidosas para que los logs del pipeline sean legibles
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("llama_index").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)

logger = logging.getLogger("disecan.app")

_BASE = Path(__file__).parent.parent          # src/
FRONTEND_DIR = _BASE / "frontend"
ASSETS_DIR = _BASE / "assets"
app = Flask(
    __name__,
    static_folder=str(FRONTEND_DIR),
    static_url_path="",
)
CORS(app)  # Desarrollo


@app.get("/")
def index():
    """Sirve la página principal"""
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.get("/assets/<path:filename>")
def assets(filename: str):
    """Sirve los assets del proyecto (logos, imágenes)."""
    return send_from_directory(str(ASSETS_DIR), filename)


@app.get("/api/health")
def health():
    """Health-check del servidor."""
    return jsonify({"status": "ok", "timestamp": time.time()})


from backend.orchestrator import ask_disecan, get_query_engine

# Precarga del motor RAG al arrancar para evitar lentitud en la primera respuesta
logger.info("[App] Inicializando motor RAG en segundo plano...")
try:
    from backend.query_analyzer import SearchPlan
    get_query_engine(SearchPlan())
    logger.info("[App] Motor RAG inicializado con éxito.")
except Exception as e:
    logger.warning(f"[App] ADVERTENCIA: Error al precargar el motor: {e}")

# Modos de operación válidos
_VALID_MODES = {"full", "linguistics_only"}

@app.post("/api/chat")
def chat():
    """
    Endpoint principal del chatbot.

    Campos del JSON de la request
    query   (str, obligatorio)  : Pregunta del usuario.
    filters (dict, opcional)    : Filtros (legislatura, fecha_desde, fecha_hasta).
    mode    (str, opcional)     : "full" | "linguistics_only"
    """
    
    data = request.get_json(silent=True) or {}
    query: str = data.get("query", "").strip()
    filters: dict = data.get("filters", {})
    mode: str = data.get("mode", "full").strip()

    if not query:
        return jsonify({"error": "El campo 'query' es obligatorio."}), 400

    if mode not in _VALID_MODES:
        return jsonify({
            "error": f"Modo '{mode}' no reconocido. Valores válidos: {sorted(_VALID_MODES)}"
        }), 400

    logger.info(f"[App] ▶ POST /api/chat | mode='{mode}' | query='{query[:80]}'")

    try:
        answer, sources, keywords = ask_disecan(query, filters, mode=mode)
        return jsonify({
            "answer": answer,
            "sources": sources,
            "keywords": keywords,
            "mode": mode,
        })
    except Exception as e:
        app.logger.error(f"Error en RAG: {e}")
        error_msg = str(e)
        if "Ollama" in error_msg or "recursos" in error_msg:
            return jsonify({
                "answer": "El motor de IA no está respondiendo. Verifica que Ollama esté activo.",
                "error": error_msg
            }), 503
        return jsonify({"error": f"Error interno: {error_msg}"}), 500


# ── Punto de entrada ───────────────────────────────────────────────────────
if __name__ == "__main__":
    # Desactivamos use_reloader para evitar bucles de reinicio en Windows con tiktoken/llama-index
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)
