import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")
from backend.db import get_legislaturas, get_documentos, get_frases_por_documento, get_palabras_por_frases_batch

print("=== Legislaturas ===")
print(get_legislaturas())

print("\n=== Documentos ===")
docs = get_documentos()
print(f"{len(docs)} documentos cargados")
for d in docs[:3]:
    print(f"  id={d['idDocumento']} | leg={d['legislatura']} | sesion={d['numSesion']} | fecha={d['fecha']} | presidente={d['presidente']}")

print("\n=== Frases del primer documento ===")
frases = get_frases_por_documento(docs[0]["idDocumento"])
print(f"{len(frases)} frases")

print("\n=== Batch palabras (primeras 3 frases) ===")
ids_3 = [f["idFrases"] for f in frases[:3]]
pals = get_palabras_por_frases_batch(ids_3)
for id_f, words in pals.items():
    texto = " ".join(p["palabra"] for p in words)
    print(f"  Frase {id_f}: {texto[:120]}...")
