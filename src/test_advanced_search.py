
import os
import sys
from pathlib import Path

# Añadir src al path
sys.path.append(str(Path(__file__).parent))

from backend.orchestrator import ask_disecan

def test_hyde_expansion():
    query = "¿Por qué está tan cara la cesta de la compra?"
    print(f"\nQUERY: {query}")
    print("="*50)
    
    response, sources, keywords = ask_disecan(query)
    
    print("\n[RESULTADOS]")
    print(f"Keywords detectadas: {keywords}")
    print(f"Respuesta resumida: {response[:200]}...")
    
    with open("test_results.txt", "w", encoding="utf-8") as f:
        f.write(f"QUERY: {query}\n")
        f.write("="*50 + "\n")
        f.write(f"\n[RESULTADOS]\n")
        f.write(f"Keywords detectadas: {keywords}\n")
        f.write(f"Respuesta resumida: {response}\n")
        
        f.write("\n[FUENTES RECUPERADAS]\n")
        for i, s in enumerate(sources):
            f.write(f"\n{i+1}. Orador: {s['speaker']} | Fecha: {s['date']} | Score: {s['score']:.4f}\n")
            f.write(f"   Contexto: {s['context']}\n")
            
        found = any("caresta" in s['context'].lower() or "copecan" in s['context'].lower() or "cesta" in s['context'].lower() for s in sources)
        if found:
            f.write("\n[EXITO] Se encontro el fragmento esperado.\n")
        else:
            f.write("\n[FALLO] No se encontro el fragmento esperado.\n")
    
    print("Prueba completada. Resultados en test_results.txt")

if __name__ == "__main__":
    test_hyde_expansion()
