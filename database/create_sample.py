"""
create_sample.py — Extrae una muestra pequeña de la BD DiSeCan y genera
un dump SQL que puede commitearse en git para pruebas en portátil.

Uso (ejecutar UNA VEZ, cuando el dump completo esté importado):
    uv run python database/create_sample.py
    uv run python database/create_sample.py --docs 5 --out database/sample/sample.sql

Genera: database/sample/sample.sql  (~5-15 MB, incluible en git)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Aseguramos acceso al módulo backend
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from backend.db import get_connection, get_cursor

OUTPUT_DEFAULT = Path(__file__).parent / "sample" / "sample.sql"


def _escape(val: object) -> str:
    """Escapa un valor para usarlo en SQL INSERT."""
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    # Para strings y dates: escapar comillas simples
    return "'" + str(val).replace("\\", "\\\\").replace("'", "\\'") + "'"


def create_sample(num_docs: int, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn, get_cursor(conn) as cur:

        # 1. Seleccionar documentos de muestra (distribuidos: primero y últimos)
        cur.execute(
            "SELECT * FROM documentos ORDER BY fecha ASC LIMIT %s",
            (num_docs,),
        )
        docs = cur.fetchall()
        if not docs:
            print("[ERROR] No hay documentos en la BD. ¿Está el dump importado?")
            sys.exit(1)

        doc_ids = [d["idDocumento"] for d in docs]
        placeholders = ", ".join(["%s"] * len(doc_ids))

        # 2. Frases de esos documentos
        cur.execute(
            f"SELECT * FROM frases WHERE idDocumento IN ({placeholders}) ORDER BY idFrases",
            doc_ids,
        )
        frases = cur.fetchall()
        frase_ids = [f["idFrases"] for f in frases]
        print(f"  Documentos: {len(docs)}, Frases: {len(frases)}")

        # 3. Palabras de esas frases (en batches para no saturar la query)
        palabras: list[dict] = []
        BATCH = 500
        for i in range(0, len(frase_ids), BATCH):
            batch_ids = frase_ids[i : i + BATCH]
            ph = ", ".join(["%s"] * len(batch_ids))
            cur.execute(
                f"SELECT * FROM palabras WHERE idFrase IN ({ph}) ORDER BY idFrase, posElementoFrase",
                batch_ids,
            )
            palabras.extend(cur.fetchall())
        print(f"  Palabras: {len(palabras)}")

        # 4. Usuarios referenciados en frases (revisada/metafora) — tabla opcional
        usuarios: list[dict] = []
        user_ids: set[str] = set()
        for f in frases:
            if f.get("revisada"):
                user_ids.add(f["revisada"])
            if f.get("metafora"):
                user_ids.add(f["metafora"])
        if user_ids:
            try:
                ph = ", ".join(["%s"] * len(user_ids))
                cur.execute(f"SELECT * FROM usuario WHERE idUsuario IN ({ph})", list(user_ids))
                usuarios = cur.fetchall()
            except Exception:
                pass  # tabla usuario no existe en este dump

    # 5. Escribir SQL
    lines: list[str] = []
    lines.append("-- DiSeCan sample dataset (autogenerado por create_sample.py)")
    lines.append(f"-- Documentos: {len(docs)}, Frases: {len(frases)}, Palabras: {len(palabras)}")
    lines.append("")
    lines.append("CREATE DATABASE IF NOT EXISTS `disecan` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    lines.append("USE `disecan`;")
    lines.append("")

    # --- documentos ---
    lines.append("DROP TABLE IF EXISTS `palabras`;")
    lines.append("DROP TABLE IF EXISTS `frases`;")
    lines.append("DROP TABLE IF EXISTS `documentos`;")
    lines.append("")

    lines.append("""CREATE TABLE `documentos` (
  `idDocumento` int NOT NULL,
  `nombreFicheroPDF` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `legislatura` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `fecha` date NOT NULL,
  `numSesion` int NOT NULL,
  `presidente` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`idDocumento`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""")


    lines.append("""CREATE TABLE `frases` (
  `idFrases` int NOT NULL AUTO_INCREMENT,
  `orador` varchar(250) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `ByteInicioFrase` int NOT NULL,
  `ByteLongFrase` int NOT NULL,
  `idDocumento` int NOT NULL,
  `revisada` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `metafora` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`idFrases`),
  CONSTRAINT `idDocumentoFK` FOREIGN KEY (`idDocumento`) REFERENCES `documentos` (`idDocumento`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""")

    lines.append("""CREATE TABLE `palabras` (
  `palabra` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `lema` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `categoria` int NOT NULL,
  `posElementoFrase` smallint NOT NULL,
  `idFrase` int NOT NULL,
  KEY `frases_idx` (`idFrase`),
  CONSTRAINT `idFraseFK` FOREIGN KEY (`idFrase`) REFERENCES `frases` (`idFrases`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""")

    def write_inserts(table: str, rows: list[dict], batch_size: int = 200) -> None:
        if not rows:
            return
        cols = ", ".join(f"`{k}`" for k in rows[0].keys())
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            vals = ",\n  ".join(
                "(" + ", ".join(_escape(v) for v in row.values()) + ")"
                for row in batch
            )
            lines.append(f"INSERT INTO `{table}` ({cols}) VALUES\n  {vals};")
        lines.append("")

    write_inserts("documentos", docs)
    if usuarios:
        write_inserts("usuario", usuarios)
    write_inserts("frases", frases)
    write_inserts("palabras", palabras, batch_size=500)

    sql_content = "\n".join(lines)
    output.write_text(sql_content, encoding="utf-8")
    size_mb = output.stat().st_size / 1_048_576
    print(f"\n[OK] Sample generado en: {output}")
    print(f"     Tamaño: {size_mb:.1f} MB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genera un sample SQL de la BD DiSeCan")
    parser.add_argument("--docs", type=int, default=10, help="Número de documentos a exportar (default: 10)")
    parser.add_argument("--out", type=str, default=str(OUTPUT_DEFAULT), help="Ruta del archivo SQL de salida")
    args = parser.parse_args()

    print(f"[create_sample] Extrayendo {args.docs} documentos...")
    create_sample(args.docs, Path(args.out))
