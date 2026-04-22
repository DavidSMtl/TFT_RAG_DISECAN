"""
test_rag.py — Prueba rápida del motor RAG simplificado.
"""
from backend.orchestrator import ask_disecan

def test_query():
    query = "¿Qué se dijo sobre Simón Bolívar?"
    print(f"[*] Probando query: {query}")
    try:
        answer, sources, keywords = ask_disecan(query)
        print("\n=== RESPUESTA ===")
        print(answer)
        print("\n=== FUENTES ===")
        for s in sources:
            print(f"- [{s['speaker']}] ({s['date']}): {s['fragment'][:100]}...")
    except Exception as e:
        print(f"[ERROR] {e}")

if __name__ == "__main__":
    test_query()
