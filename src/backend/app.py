"""
app.py — API REST encargada de comunicar el RAG con el frontend.
"""
from __future__ import annotations
import logging
import time
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from backend.orchestrator import ask_disecan, get_query_engine
from backend.query_analyzer import SearchPlan

# ── Configuración de Logs ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Silenciar logs ruidosos de librerías de terceros
for logger_name in ["httpx", "httpcore", "llama_index", "chromadb"]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

logger = logging.getLogger("disecan.app")

# ── Configuración de Flask ────────────────────────────────────────────────────
_BASE = Path(__file__).parent.parent
FRONTEND_DIR = _BASE / "frontend"
ASSETS_DIR = _BASE / "assets"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
CORS(app)

# Precarga del motor RAG para evitar lentitud en la primera respuesta
logger.info("[App] Inicializando motor RAG en segundo plano...")
try:
    get_query_engine(SearchPlan())
    logger.info("[App] Motor RAG inicializado con éxito.")
except Exception as e:
    logger.warning(f"[App] Error al precargar el motor: {e}")

# ── Endpoints Base ────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")

@app.get("/assets/<path:filename>")
def assets(filename: str):
    return send_from_directory(str(ASSETS_DIR), filename)

@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "timestamp": time.time()})

# ── Endpoint RAG ──────────────────────────────────────────────────────────────
@app.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    filters = data.get("filters", {})
    mode = data.get("mode", "full").strip()

    if not query:
        return jsonify({"error": "El campo 'query' es obligatorio."}), 400

    if mode not in {"full", "linguistics_only"}:
        return jsonify({"error": "Modo no reconocido. Use 'full' o 'linguistics_only'"}), 400

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
        logger.error(f"[App] Error procesando consulta: {e}")
        if "Ollama" in str(e) or "recursos" in str(e):
            return jsonify({
                "answer": "El motor de IA no está respondiendo. Verifica que Ollama esté activo.",
                "error": str(e)
            }), 503
        return jsonify({"error": f"Error interno: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)
