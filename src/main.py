"""
DiSeCan RAG — Entry point
Arranca el servidor Flask. Ejecutar con:
    uv run python src/main.py
"""
from backend.app import app

if __name__ == "__main__":
    # use_reloader=False evita bucles de reinicio infinito en Windows al cargar modelos pesados
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)
