"""
verify.py — Valida la integridad del sample armonizado.
Comprueba que los punteros del SQL apuntan al texto correcto en documentos_sample.txt.
"""
import re
from pathlib import Path

def verify_harmonized_sample():
    sql_path = Path('database/sample/sample.sql')
    txt_path = Path('data/corpus/documentos_sample.txt')
    
    if not sql_path.exists() or not txt_path.exists():
        print("[ERROR] No se encuentran los archivos del sample en database/sample/.")
        return

    print(f"[*] Analizando integridad del sample...")
    with open(sql_path, 'r', encoding='utf-8') as f:
        sql = f.read()
    
    # Regex robusta para extraer: idFrases, ByteInicio, ByteLong
    # INSERT INTO `frases` (...) VALUES (id, 'Orador', Start, Len, ...);
    pattern = re.compile(r"INSERT INTO `frases` \([^)]+\) VALUES \((\d+), '.*?', (\d+), (\d+), .*?\);")
    matches = list(pattern.finditer(sql))
    
    if not matches:
        print("[WARN] No se detectaron líneas de INSERT en sample.sql.")
        return

    print(f"[*] Verificando una muestra de {min(5, len(matches))} párrafos...")
    
    with open(txt_path, "rb") as f_txt:
        for m in matches[:5]:
            fid, b_start, b_len = m.groups()
            b_start, b_len = int(b_start), int(b_len)
            
            f_txt.seek(b_start)
            raw = f_txt.read(b_len)
            text = raw.decode("cp1252", errors="ignore")
            
            print(f"\n[Frase {fid}] Start:{b_start} Len:{b_len}")
            print(f">> \"{text[:150]}...\"")

if __name__ == "__main__":
    verify_harmonized_sample()
