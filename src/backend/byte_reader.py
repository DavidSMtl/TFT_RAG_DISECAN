import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Configuración por defecto (basada en el análisis de DiSeCan)
CORPUS_FILE_PATH = os.getenv("CORPUS_FILE_PATH", "./data/corpus/documentos.txt")
PHRASES_FILE_PATH = os.getenv("PHRASES_FILE_PATH", "./data/corpus/frases.txt")
ENCODING = "cp1252"  # Codificación original de DiSeCan (ISO-8859-1)

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
                # Usamos cp1252 para respetar la codificación original de DiSeCan
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

def test_reader():
    """Prueba de lectura directa con offsets conocidos."""
    reader = ByteTextReader()
    # Frase 1: Offset 0, Len 71 en el sistema original
    print(f"Probando lectura directa de {CORPUS_FILE_PATH}...")
    texto = reader.get_text_by_offsets(0, 71)
    if texto:
        print(f"Texto recuperado (Offset 0):\n{texto}")
    else:
        print("No se pudo recuperar el texto. Verifica la ruta en el .env.")

if __name__ == "__main__":
    test_reader()
