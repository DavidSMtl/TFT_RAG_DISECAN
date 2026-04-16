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


import asyncio
from backend.orchestrator import ask_disecan

@app.post("/api/chat")
def chat():
    """
    Endpoint principal del chatbot (Síncrono para evitar problemas de dependencias).
    """
    data = request.get_json(silent=True) or {}
    query: str = data.get("query", "").strip()
    filters: dict = data.get("filters", {})

    if not query:
        return jsonify({"error": "El campo 'query' es obligatorio."}), 400

    try:
        # ── Ejecución de la lógica asíncrona en un entorno síncrono ──────
        # Creamos un nuevo loop si es necesario o usamos asyncio.run
        answer, sources = asyncio.run(ask_disecan(query, filters))
        # ──────────────────────────────────────────────────────────────────
        return jsonify({"answer": answer, "sources": sources})
    except Exception as e:
        app.logger.error(f"Error en RAG: {e}")
        return jsonify({"error": f"Error interno: {str(e)}"}), 500


# ── Punto de entrada ───────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
