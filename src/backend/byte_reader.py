import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Configuración por defecto (basada en el análisis de DiSeCan)
CORPUS_FILE_PATH = os.getenv("CORPUS_FILE_PATH", "./data/corpus/documentos.txt")
PHRASES_FILE_PATH = os.getenv("PHRASES_FILE_PATH", "./data/corpus/frases.txt")
ENCODING = "latin-1"  # Los offsets originales de DiSeCan asumen Latin-1 (1 byte = 1 char)

def fix_encoding(s: str) -> str:
    """
    Corrige strings con codificación rota múltiple o mojibake (ej. Ã± -> ñ).
    """
    if not isinstance(s, str) or not s:
        return s
    
    # 1. Diccionario de emergencia para mojibake común de DiSeCan/Parlamento
    # Estos casos a veces no se arreglan con encode/decode simple si hay caracteres de control
    replacements = {
        "Ã¡": "á", "Ã©": "é", "Ã­": "í", "Ã³": "ó", "Ãº": "ú",
        "Ã±": "ñ", "Ã‘": "Ñ", "Ã\x81": "Á", "Ã\x89": "É", "Ã\x8d": "Í",
        "Ã\x93": "Ó", "Ã\x9a": "Ú", "Ã¼": "ü", "Ã\xbf": "¿", "Â¡": "¡"
    }
    
    # Aplicar reemplazos manuales primero (son los más seguros)
    for old, new in replacements.items():
        s = s.replace(old, new)

    # 2. Intentar arreglo recursivo por si hay más niveles
    current = s
    for _ in range(3):
        try:
            # Probamos a revertir: lo que parece cp1252 era en realidad UTF-8
            test_s = current.encode('cp1252').decode('utf-8')
            if test_s == current: break
            current = test_s
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
            
    # Limpieza final de espacios raros o caracteres de control que ensucian la búsqueda
    return current.strip()

class ByteTextReader:
    """
    Lector de texto basado en offsets de bytes para el corpus de DiSeCan.
    Extrae texto directamente de documentos.txt usando los punteros de MySQL.
    """
    
    def __init__(self, documentos_path: Optional[str] = None):
        self.documentos_path = Path(documentos_path or CORPUS_FILE_PATH)
        
        if not self.documentos_path.exists():
            print(f"Advertencia: No se encuentra documentos.txt en {self.documentos_path}")

    def get_text_by_offsets(self, b_start: int, b_len: int) -> str:
        """
        Lee un fragmento de texto (frase o párrafo) directamente de documentos.txt.
        """
        if not self.documentos_path.exists():
            return ""
            
        try:
            with open(self.documentos_path, "rb") as f:
                f.seek(b_start)
                raw = f.read(b_len)
                # Latin-1: 1 byte = 1 char, los offsets son exactos y el texto sale perfecto
                return raw.decode(ENCODING, errors="ignore").strip()
        except Exception as e:
            print(f"Error leyendo documentos.txt en offset {b_start}: {e}")
        return ""

    def get_paragraph(self, b_start: int, b_len: int) -> str:
        """
        Alias para get_text_by_offsets, ya que en el dump actual el offset
        de la frase a menudo apunta al párrafo completo.
        """
        return self.get_text_by_offsets(b_start, b_len)
