"""
test_disecan_search.py — Prueba la búsqueda lingüística DISECAN directamente
contra la base de datos MySQL, sin depender del RAG ni de ChromaDB.

Uso (desde la raíz del proyecto):
    python -m src.scripts.test_disecan_search

O con patrones concretos:
    python -m src.scripts.test_disecan_search "<sustantivo>" "[hablar]" "agua 2 <sustantivo>"
"""
from __future__ import annotations
import sys
import os
import logging

# ── Configurar sys.path para importar desde src/ ──────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SRC  = os.path.join(_ROOT, "src")
# Añadir src/ al path para que 'backend' sea importable directamente
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Activar logs detallados para ver el SQL generado
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s [%(name)s] %(message)s",
)

from backend.db import linguistic_search_pattern, linguistic_search  # noqa: E402

# ── Casos de prueba por defecto ───────────────────────────────────────────────
DEFAULT_CASES = [
    # Formato: (descripción, patrón, ordered)
    ("Categoría simple",              "<sustantivo>",            True),
    ("Lema simple",                   "[hablar]",                True),
    ("Lema + categoría",              "[hablar:verbo]",          True),
    ("Palabra exacta",                "agua",                    True),
    ("Dos lemas adyacentes",          "[hablar] <sustantivo>",   True),
    ("Dos lemas con distancia 2",     "[hablar] 2 <sustantivo>", True),
    ("Palabra con comodín",           "presupuest*",             True),
    ("Lema con comodín",              "[presupuest*]",           True),
    ("Palabra:cat",                   "agua:sustantivo",         True),
    ("Sin orden, dos términos",       "[hablar] <sustantivo>",   False),
]


def run_test(desc: str, pattern: str, ordered: bool, top_k: int = 10) -> None:
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"TEST : {desc}")
    print(f"PATRÓN: '{pattern}'  |  ordered={ordered}")
    print(sep)
    try:
        results = linguistic_search_pattern(pattern, top_k=top_k, ordered=ordered)
        if results:
            print(f"✔ {len(results)} resultado(s):")
            for i, r in enumerate(results[:5], 1):
                print(f"  [{i}] id_frase={r['id_frase']} | doc={r['id_documento']} | orador={r.get('orador', '?')!r}")
        else:
            print("✗ Sin resultados")
    except Exception as e:
        print(f"✗ EXCEPCIÓN: {e}")


def main():
    # Si se pasan argumentos en línea de comandos, usarlos como patrones
    if len(sys.argv) > 1:
        for pattern in sys.argv[1:]:
            run_test(f"CLI: {pattern}", pattern, ordered=True)
    else:
        for desc, pattern, ordered in DEFAULT_CASES:
            run_test(desc, pattern, ordered)

    print("\n" + "═" * 60)
    print("Pruebas finalizadas.")


if __name__ == "__main__":
    main()
