"""
API REST encargada de comunicar el RAG con el frontend.
"""
from __future__ import annotations

import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

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
    """Sirve la SPA del chatbot."""
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
print("[App] Inicializando motor RAG en segundo plano...")
try:
    from backend.query_analyzer import SearchPlan
    get_query_engine(SearchPlan())
    print("[App] Motor RAG inicializado con éxito.")
except Exception as e:
    print(f"[App] ADVERTENCIA: Error al precargar el motor: {e}")

@app.post("/api/chat")
def chat():
    """
    Endpoint principal del chatbot (100% síncrono).
    """
    data = request.get_json(silent=True) or {}
    query: str = data.get("query", "").strip()
    filters: dict = data.get("filters", {})

    if not query:
        return jsonify({"error": "El campo 'query' es obligatorio."}), 400

    try:
        answer, sources, keywords = ask_disecan(query, filters)
        return jsonify({
            "answer": answer, 
            "sources": sources,
            "keywords": keywords
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
