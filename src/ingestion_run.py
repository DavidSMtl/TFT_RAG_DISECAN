"""
ingestion_run.py — Script para ejecutar la ingestión desde la línea de comandos.

Uso:
    uv run python src/ingestion_run.py                   # Todo el corpus
    uv run python src/ingestion_run.py --legislatura X   # Solo una legislatura
    uv run python src/ingestion_run.py --force           # Re-ingestar aunque ya existan chunks
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Aseguramos que la raíz del proyecto esté en el PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from backend.ingestion import run_ingestion


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline de ingestión DiSeCan -> ChromaDB")
    parser.add_argument("--legislatura", type=str, default=None, help="Filtrar por legislatura (ej: X)")
    parser.add_argument("--fecha-desde", type=str, default=None, help="Fecha inicio YYYY-MM-DD")
    parser.add_argument("--fecha-hasta", type=str, default=None, help="Fecha fin YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="Re-ingestar aunque ya existan chunks")
    parser.add_argument("--quiet", action="store_true", help="Reducir output")
    args = parser.parse_args()

    filtros: dict = {}
    if args.legislatura:
        filtros["legislatura"] = args.legislatura
    if args.fecha_desde:
        filtros["fecha_desde"] = args.fecha_desde
    if args.fecha_hasta:
        filtros["fecha_hasta"] = args.fecha_hasta

    total = run_ingestion(filtros=filtros, force=args.force, verbose=not args.quiet)
    print(f"\nTotal chunks procesados: {total}")


if __name__ == "__main__":
    main()
