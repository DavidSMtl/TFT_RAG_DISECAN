import sys
from pathlib import Path

# Agregar src al PYTHONPATH
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from backend.db import get_connection

def clean_database():
    print("[*] Conectando a la base de datos para la limpieza de codificación...")
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Limpiar tabla palabras
        print("[*] Limpiando columna 'lema' y 'palabra' en la tabla 'palabras' (~450k filas)...")
        sql_palabras = """
            UPDATE palabras 
            SET lema = CONVERT(CAST(CONVERT(lema USING latin1) AS binary) USING utf8mb4),
                palabra = CONVERT(CAST(CONVERT(palabra USING latin1) AS binary) USING utf8mb4)
            WHERE lema LIKE '%Ã%' OR palabra LIKE '%Ã%'
        """
        cursor.execute(sql_palabras)
        print(f"    - Filas modificadas en 'palabras': {cursor.rowcount}")
        
        # 2. Limpiar tabla frases
        print("[*] Limpiando columna 'orador' en la tabla 'frases'...")
        sql_frases = """
            UPDATE frases 
            SET orador = CONVERT(CAST(CONVERT(orador USING latin1) AS binary) USING utf8mb4)
            WHERE orador LIKE '%Ã%'
        """
        cursor.execute(sql_frases)
        print(f"    - Filas modificadas en 'frases': {cursor.rowcount}")
        
        # 3. Limpiar tabla documentos
        print("[*] Limpiando columna 'presidente' en la tabla 'documentos'...")
        sql_documentos = """
            UPDATE documentos 
            SET presidente = CONVERT(CAST(CONVERT(presidente USING latin1) AS binary) USING utf8mb4)
            WHERE presidente LIKE '%Ã%'
        """
        cursor.execute(sql_documentos)
        print(f"    - Filas modificadas en 'documentos': {cursor.rowcount}")
        
        conn.commit()
        print("[+] Limpieza de base de datos completada con exito!")

if __name__ == "__main__":
    try:
        clean_database()
    except Exception as e:
        print(f"[ERROR] No se pudo limpiar la base de datos: {e}")
