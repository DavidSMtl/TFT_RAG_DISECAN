import argparse
import sys
import os
from pathlib import Path

# Aseguramos acceso al módulo backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.db import get_connection, get_cursor
from backend.byte_reader import fix_encoding, CORPUS_FILE_PATH, PHRASES_FILE_PATH

def _escape(val: object) -> str:
    """Escapa valores para SQL INSERT."""
    if val is None: return "NULL"
    if isinstance(val, (int, float)): return str(val)
    return "'" + str(val).replace("\\", "\\\\").replace("'", "\\'") + "'"

def create_harmonized_sample(num_docs: int, output_sql: Path):
    print(f"[*] Iniciando muestreo armonizado de {num_docs} documentos...")
    
    # Forzamos las rutas de los archivos FULL como fuente para el muestreo
    CORPUS_FILE = Path("data/corpus/documentos.txt")
    PHRASES_FILE = Path("data/corpus/frases.txt")

    if not PHRASES_FILE.exists():
        print(f"[ERROR] No se encuentra {PHRASES_FILE}")
        return

    # 1. Obtener documentos base de MySQL
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute("SELECT * FROM documentos ORDER BY fecha ASC LIMIT %s", (num_docs,))
        docs = cur.fetchall()
        if not docs:
            print("[ERROR] No hay documentos en la BD.")
            return

        # Limpiamos nombres de presidentes
        for d in docs:
            d["presidente"] = fix_encoding(d.get("presidente", ""))

        doc_ids = [d["idDocumento"] for d in docs]
        placeholders = ", ".join(["%s"] * len(doc_ids))

        cur.execute(f"SELECT * FROM frases WHERE idDocumento IN ({placeholders}) ORDER BY idFrases", doc_ids)
        frases_db = cur.fetchall()
        
        frase_ids = {f["idFrases"]: f for f in frases_db}
        print(f"[*] Encontradas {len(frases_db)} frases en los {num_docs} documentos en MySQL.")

    # 2. ESCANEO DE frases.txt (ARMONIZACIÓN DE OFFSETS)
    print(f"[*] Escaneando {PHRASES_FILE.name} para armonizar offsets y limpiar oradores...")
    harmonized_frases = []
    max_physical_offset = 0
    max_phrase_file_pos = 0
    
    with open(PHRASES_FILE, "rb") as f:
        for line_bytes in f:
            try:
                # Escaneamos como latin-1 para armonizar con el sistema original
                line = line_bytes.decode("utf-8", errors="replace")
                parts = line.split('\t')
                if not parts or not parts[0].isdigit():
                    continue
                
                fid = int(parts[0])
                if fid in frase_ids:
                    # Extraer offsets del archivo físico de frases
                    # Formato: ID \t TEXTO \t START \t LEN
                    b_start = int(parts[2])
                    b_len = int(parts[3])
                    
                    # Crear el registro armonizado
                    f_data = frase_ids[fid].copy()
                    f_data["ByteInicioFrase"] = b_start
                    f_data["ByteLongFrase"] = b_len
                    # LIMPIEZA CRÍTICA: Corregimos el orador aquí mismo
                    f_data["orador"] = fix_encoding(f_data.get("orador", "DESCONOCIDO"))
                    
                    harmonized_frases.append(f_data)
                    
                    # Actualizar límites para el truncamiento de documentos.txt
                    max_physical_offset = max(max_physical_offset, b_start + b_len)
                    max_phrase_file_pos = f.tell()
                    
                    if fid >= max(frase_ids.keys()):
                        break
            except Exception:
                continue

    print(f"[*] Armonización completada. {len(harmonized_frases)} frases mapeadas físicamente.")

    # 3. Obtener palabras (lemas) para las frases
    sampled_frase_ids = [f["idFrases"] for f in harmonized_frases]
    palabras = []
    if sampled_frase_ids:
        BATCH = 1000
        with get_connection() as conn, get_cursor(conn) as cur:
            for i in range(0, len(sampled_frase_ids), BATCH):
                batch = sampled_frase_ids[i:i+BATCH]
                ph = ", ".join(["%s"] * len(batch))
                cur.execute(f"SELECT * FROM palabras WHERE idFrase IN ({ph})", batch)
                batch_pals = cur.fetchall()
                # Limpiar tildes en lemas y palabras
                for p in batch_pals:
                    p["palabra"] = fix_encoding(p.get("palabra", ""))
                    p["lema"] = fix_encoding(p.get("lema", ""))
                palabras.extend(batch_pals)

    # 4. Generar SQL
    output_sql.parent.mkdir(parents=True, exist_ok=True)
    cols_docs = ["idDocumento", "nombreFicheroPDF", "legislatura", "fecha", "numSesion", "presidente"]
    cols_frases = ["idFrases", "orador", "ByteInicioFrase", "ByteLongFrase", "idDocumento", "revisada", "metafora"]
    cols_palabras = ["palabra", "lema", "categoria", "posElementoFrase", "idFrase"]

    lines = [
        "SET FOREIGN_KEY_CHECKS = 0;",
        "DROP TABLE IF EXISTS `palabras`;", "DROP TABLE IF EXISTS `frases`;", "DROP TABLE IF EXISTS `documentos`;",
        "CREATE TABLE `documentos` (idDocumento int PRIMARY KEY, nombreFicheroPDF varchar(100), legislatura varchar(10), fecha date, numSesion int, presidente varchar(100)) ENGINE=InnoDB;",
        "CREATE TABLE `frases` (idFrases int PRIMARY KEY, orador varchar(250), ByteInicioFrase int, ByteLongFrase int, idDocumento int, revisada varchar(50), metafora varchar(50)) ENGINE=InnoDB;",
        "CREATE TABLE `palabras` (palabra varchar(50), lema varchar(50), categoria int, posElementoFrase smallint, idFrase int) ENGINE=InnoDB;",
        ""
    ]

    def write_inserts(table, rows, valid_cols, batch_size=500):
        if not rows: return
        col_str = ", ".join(f"`{c}`" for c in valid_cols)
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i+batch_size]
            values = [f"({', '.join(_escape(r.get(c)) for c in valid_cols)})" for r in batch]
            lines.append(f"INSERT INTO `{table}` ({col_str}) VALUES {', '.join(values)};")

    write_inserts("documentos", docs, cols_docs)
    write_inserts("frases", harmonized_frases, cols_frases)
    write_inserts("palabras", palabras, cols_palabras)
    lines.append("SET FOREIGN_KEY_CHECKS = 1;")
    output_sql.write_text("\n".join(lines), encoding="utf-8")

    # 5. TRUNCAMIENTO FÍSICO
    sample_docs_path = Path("data/corpus/documentos_sample.txt")
    sample_phrases_path = Path("data/corpus/frases_sample.txt")

    with open(CORPUS_FILE, "rb") as f_in, open(sample_docs_path, "wb") as f_out:
        f_out.write(f_in.read(max_physical_offset))
    
    with open(PHRASES_FILE, "rb") as f_in, open(sample_phrases_path, "wb") as f_out:
        f_out.write(f_in.read(max_phrase_file_pos))

    print(f"\n[ÉXITO] Sample armonizado generado:")
    print(f"  - SQL: {output_sql} (Con oradores y lemas corregidos)")
    print(f"  - TXT: {sample_docs_path}")
    print(f"  - Index: {sample_phrases_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", type=int, default=10)
    parser.add_argument("--out", type=str, default="database/sample/sample.sql")
    args = parser.parse_args()
    create_harmonized_sample(args.docs, Path(args.out))
