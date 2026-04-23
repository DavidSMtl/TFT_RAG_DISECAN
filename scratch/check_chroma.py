import sys
from pathlib import Path
from dotenv import load_dotenv

# Añadimos src al path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from backend.chroma_store import get_collection, get_all_chunks

def verify_chroma():
    load_dotenv()
    col = get_collection()
    total = col.count()
    
    print(f"=== Verificación de ChromaDB ===")
    print(f"Total de chunks en la colección: {total}")
    
    if total == 0:
        print("La colección está vacía. Ejecuta la ingesta primero.")
        return

    # Obtenemos una muestra
    chunks = get_all_chunks()
    sample_size = min(5, len(chunks))
    
    print(f"\nMostrando una muestra de {sample_size} chunks:\n")
    
    for i in range(sample_size):
        c = chunks[i]
        cid = c['id']
        meta = c['metadata']
        text = c['document'][:100].replace('\n', ' ') + "..."
        
        print(f"[{i+1}] ID: {cid}")
        print(f"    - Orador: {meta.get('orador')}")
        print(f"    - Documento ID: {meta.get('id_documento')}")
        print(f"    - Frase Inicio: {meta.get('id_frase_inicio')}")
        print(f"    - Texto: {text}")
        
        # Validación de integridad del ID
        expected_id = f"c_{meta.get('id_documento')}_{meta.get('id_frase_inicio')}"
        if cid == expected_id:
            print(f"    [OK] ID Bien formado y consistente.")
        else:
            print(f"    [ERROR] ID inconsistente. Esperado: {expected_id}")
        print("-" * 40)

if __name__ == "__main__":
    verify_chroma()
