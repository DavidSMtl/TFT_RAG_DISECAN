import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Configuración por defecto (basada en el análisis de DiSeCan)
CORPUS_FILE_PATH = os.getenv("CORPUS_FILE_PATH", "./data/corpus/documentos.txt")
PHRASES_FILE_PATH = os.getenv("PHRASES_FILE_PATH", "./data/corpus/frases.txt")
ENCODING = "utf-8"  # El corpus físico está en UTF-8; los offsets de byte siguen siendo correctos

def fix_encoding(s: str) -> str:
    """
    Limpia espacios en blanco y valida el tipo de cadena.
    """
    if not isinstance(s, str) or not s:
        return s
    return s.strip()

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
