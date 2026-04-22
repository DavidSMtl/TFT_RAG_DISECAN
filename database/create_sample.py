"""
create_sample.py — Genera un sample de DiSeCan armonizando el SQL con los archivos físicos.
Extrae los offsets reales de frases.txt para que el dump sea fiel a los archivos originales.
"""
import argparse
import sys
import os
from pathlib import Path
import re

# Aseguramos acceso al módulo backend
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from backend.db import get_connection, get_cursor

def _escape(val: object) -> str:
    """Escapa valores para SQL INSERT."""
    if val is None: return "NULL"
    if isinstance(val, (int, float)): return str(val)
    return "'" + str(val).replace("\\", "\\\\").replace("'", "\\'") + "'"

def create_harmonized_sample(num_docs: int, output_sql: Path):
    print(f"[*] Iniciando muestreo armonizado de {num_docs} documentos...")
    
    # Rutas de archivos originales
    from backend.byte_reader import CORPUS_FILE_PATH, PHRASES_FILE_PATH
    CORPUS_FILE = Path(CORPUS_FILE_PATH)
    PHRASES_FILE = Path(PHRASES_FILE_PATH)

    # 1. Obtener documentos y frases base de MySQL
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute("SELECT * FROM documentos ORDER BY fecha ASC LIMIT %s", (num_docs,))
        docs = cur.fetchall()
        if not docs:
            print("[ERROR] No hay documentos en la BD.")
            return

        doc_ids = [d["idDocumento"] for d in docs]
        placeholders = ", ".join(["%s"] * len(doc_ids))

        cur.execute(f"SELECT * FROM frases WHERE idDocumento IN ({placeholders}) ORDER BY idFrases", doc_ids)
        frases_db = cur.fetchall()
        
        frase_ids = {f["idFrases"]: f for f in frases_db}
        print(f"[*] Encontradas {len(frases_db)} frases en los {num_docs} documentos en MySQL.")

    # 2. ESCANEO DE frases.txt (ARMONIZACIÓN)
    # Buscamos los offsets REALES en el archivo físico para que coincidan con documentos.txt
    print(f"[*] Escaneando {PHRASES_FILE.name} para armonizar offsets...")
    harmonized_frases = []
    max_physical_offset = 0
    max_phrase_file_pos = 0
    
    with open(PHRASES_FILE, "rb") as f:
        for line_bytes in f:
            try:
                line = line_bytes.decode("cp1252", errors="ignore")
                parts = line.split('\t')
                if not parts or not parts[0].isdigit():
                    continue
                
                fid = int(parts[0])
                if fid in frase_ids:
                    # Extraer offsets del archivo físico
                    # Formato: ID \t TEXTO \t START \t LEN
                    b_start = int(parts[2])
                    b_len = int(parts[3])
                    
                    # Crear el registro armonizado (usamos la data de DB pero los offsets del archivo)
                    f_data = frase_ids[fid].copy()
                    f_data["ByteInicioFrase"] = b_start
                    f_data["ByteLongFrase"] = b_len
                    harmonized_frases.append(f_data)
                    
                    # Actualizar límites para el truncamiento
                    max_physical_offset = max(max_physical_offset, b_start + b_len)
                    max_phrase_file_pos = f.tell()
                    
                    # Si ya encontramos todas las frases de la DB, podríamos parar (optimización)
                    # Pero en DiSeCan las frases suelen estar ordenadas, así que si pasamos el ID máximo paramos.
                    if fid > max(frase_ids.keys()):
                        break
            except Exception as e:
                continue

    print(f"[*] Armonización completada. {len(harmonized_frases)} frases mapeadas físicamente.")
    if len(harmonized_frases) < len(frases_db):
        print(f"[WARN] No se encontraron todas las frases en frases.txt ({len(harmonized_frases)}/{len(frases_db)})")

    # 3. Obtener palabras para las frases armonizadas
    sampled_frase_ids = [f["idFrases"] for f in harmonized_frases]
    palabras = []
    if sampled_frase_ids:
        BATCH = 1000
        with get_connection() as conn, get_cursor(conn) as cur:
            for i in range(0, len(sampled_frase_ids), BATCH):
                batch = sampled_frase_ids[i:i+BATCH]
                ph = ", ".join(["%s"] * len(batch))
                cur.execute(f"SELECT * FROM palabras WHERE idFrase IN ({ph})", batch)
                palabras.extend(cur.fetchall())

    # 4. Generar SQL sample.sql
    output_sql.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "SET FOREIGN_KEY_CHECKS = 0;",
        "DROP TABLE IF EXISTS `palabras`;",
        "DROP TABLE IF EXISTS `frases`;",
        "DROP TABLE IF EXISTS `documentos`;",
        "",
        "CREATE TABLE `documentos` (idDocumento int PRIMARY KEY, nombreFicheroPDF varchar(100), legislatura varchar(10), fecha date, numSesion int, presidente varchar(100)) ENGINE=InnoDB;",
        "CREATE TABLE `frases` (idFrases int PRIMARY KEY, orador varchar(250), ByteInicioFrase int, ByteLongFrase int, idDocumento int) ENGINE=InnoDB;",
        "CREATE TABLE `palabras` (palabra varchar(50), lema varchar(50), categoria int, posElementoFrase smallint, idFrase int) ENGINE=InnoDB;",
        ""
    ]

    def write_inserts(table, rows):
        if not rows: return
        cols = ", ".join(f"`{k}`" for k in rows[0].keys())
        for row in rows:
            vals = ", ".join(_escape(v) for v in row.values())
            lines.append(f"INSERT INTO `{table}` ({cols}) VALUES ({vals});")

    write_inserts("documentos", docs)
    write_inserts("frases", harmonized_frases)
    write_inserts("palabras", palabras)
    lines.append("SET FOREIGN_KEY_CHECKS = 1;")
    output_sql.write_text("\n".join(lines), encoding="utf-8")

    # 5. TRUNCAMIENTO FÍSICO BIT-PERFECT
    # Recortamos los archivos originales exactamente donde terminan nuestras frases armonizadas
    sample_docs_path = Path("data/corpus/documentos_sample.txt")
    sample_phrases_path = Path("data/corpus/frases_sample.txt")

    with open(CORPUS_FILE, "rb") as f_in, open(sample_docs_path, "wb") as f_out:
        f_out.write(f_in.read(max_physical_offset))
    
    with open(PHRASES_FILE, "rb") as f_in, open(sample_phrases_path, "wb") as f_out:
        f_out.write(f_in.read(max_phrase_file_pos))

    print(f"\n[ÉXITO] Sample generado:")
    print(f"  - SQL: {output_sql} (Offsets armonizados con archivos físicos)")
    print(f"  - TXT: {sample_docs_path} ({max_physical_offset} bytes)")
    print(f"  - Index: {sample_phrases_path} ({max_phrase_file_pos} bytes)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", type=int, default=5)
    parser.add_argument("--out", type=str, default="database/sample/sample.sql")
    args = parser.parse_args()
    create_harmonized_sample(args.docs, Path(args.out))
