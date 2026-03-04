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


@app.post("/api/chat")
def chat():
    """
    Endpoint principal del chatbot.

    Request body (JSON):
        query   : str   — pregunta del usuario
        filters : dict  — filtros de búsqueda (legislatura, orador, sesión, fecha)

    Response (JSON):
        answer  : str        — respuesta generada
        sources : list[dict] — fragmentos del Diario de Sesiones usados como contexto
    """
    data = request.get_json(silent=True) or {}
    query: str = data.get("query", "").strip()
    filters: dict = data.get("filters", {})

    if not query:
        return jsonify({"error": "El campo 'query' es obligatorio."}), 400

    # ── TODO: sustituir por llamada real a LlamaIndex ──────────────────────
    answer, sources = _mock_rag(query, filters)
    # ──────────────────────────────────────────────────────────────────────

    return jsonify({"answer": answer, "sources": sources})


# ── Mock RAG (placeholder hasta integrar LlamaIndex) ──────────────────────
def _mock_rag(query: str, filters: dict) -> tuple[str, list[dict]]:
    """Devuelve una respuesta simulada para probar el frontend end-to-end."""
    answer = (
        f"[Respuesta mock para: «{query}»] "
        "Según el Diario de Sesiones, el Diputado X propuso una enmienda "
        "para aumentar las ayudas al alquiler en el marco del debate "
        "sobre política de vivienda urgente."
    )
    sources = [
        {
            "fragment": (
                "«...es imperativo que este Parlamento apruebe el decreto "
                "de vivienda urgente antes del próximo período de sesiones...»"
            ),
            "speaker": "Diputado X",
            "date": "12/01/2024",
            "legislature": filters.get("legislatura", "X Legislatura"),
            "pdf_url": "#",
        }
    ]
    return answer, sources


# ── Punto de entrada ───────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
