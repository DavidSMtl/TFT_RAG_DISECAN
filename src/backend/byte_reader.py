import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Configuración por defecto (basada en el análisis de DiSeCan)
# Documentos.txt  → el corpus de texto completo con los párrafos reales
# Frases.txt      → el índice de punteros con las frases cortas y los offsets de párrafo
CORPUS_FILE_PATH  = os.getenv("CORPUS_FILE_PATH",  "./data/corpus/documentos_sample.txt")
PHRASES_FILE_PATH = os.getenv("PHRASES_FILE_PATH", "./data/corpus/frases_sample.txt")

# El corpus está en UTF-8; los offsets de byte siguen siendo exactos
ENCODING = "utf-8"


def fix_encoding(s: str) -> str:
    """
    Arregla problemas de codificación (mojibake) típicos de MySQL en Windows
    y limpia espacios en blanco.
    """
    if not isinstance(s, str) or not s:
        return s

    s = s.strip()
    try:
        # Intenta arreglar la doble codificación típica (ej: 'JesÃºs' -> 'Jesús')
        return s.encode('latin1').decode('utf8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        # Si falla, devuelve el string original
        return s


class ByteTextReader:
    """
    Lector de texto basado en offsets de bytes para el corpus de DiSeCan.

    Replica exactamente el flujo del BuscadorCongreso (InformationExtractor.cs):
      1. FrasesFileManagement  → lee Frases.txt con los offsets de MySQL para obtener
                                  el texto de la frase corta Y los offsets del párrafo.
      2. ParrafosFileManagement → lee Documentos.txt con los offsets del párrafo para
                                   obtener el contexto ampliado.
    """

    def __init__(
        self,
        documentos_path: Optional[str] = None,
        frases_path: Optional[str] = None,
    ):
        self.documentos_path = Path(documentos_path or CORPUS_FILE_PATH)
        self.frases_path     = Path(frases_path     or PHRASES_FILE_PATH)

        if not self.documentos_path.exists():
            print(f"[ByteReader] WARN: No se encuentra documentos.txt en {self.documentos_path}")
        if not self.frases_path.exists():
            print(f"[ByteReader] WARN: No se encuentra frases.txt en {self.frases_path}")

    # ── PASO 1: Frases.txt ────────────────────────────────────────────────────

    def get_sentence_and_paragraph_offsets(self, b_start: int, b_len: int) -> dict:
        """
        Lee una línea de Frases.txt usando los offsets de MySQL
        (ByteInicioFrase / ByteLongFrase) — igual que FrasesFileManagement.cs.

        Formato de Frases.txt (TSV):
            idFrase \\t Frase \\t ByteInicioParrafo \\t ByteLongParrafo \\t

        Retorna un dict con:
            sentence    → texto de la frase corta
            b_par_start → ByteInicioParrafo (offset en Documentos.txt)
            b_par_len   → ByteLongParrafo   (longitud en Documentos.txt)
        """
        empty = {"sentence": "", "b_par_start": 0, "b_par_len": 0}

        if not self.frases_path.exists():
            return empty

        try:
            with open(self.frases_path, "rb") as f:
                f.seek(b_start)
                raw = f.read(b_len)

            # El fichero puede estar en UTF-8 o Latin-1 dependiendo del origen
            for enc in (ENCODING, "latin1", "cp1252"):
                try:
                    line = raw.decode(enc).strip()
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return empty

            parts = line.split("\t")
            if len(parts) < 4:
                return empty

            sentence    = parts[1].strip()
            b_par_start = int(parts[2]) if parts[2].strip().isdigit() else 0
            b_par_len   = int(parts[3]) if parts[3].strip().isdigit() else 0

            return {"sentence": sentence, "b_par_start": b_par_start, "b_par_len": b_par_len}

        except Exception as e:
            print(f"[ByteReader] Error leyendo Frases.txt en offset {b_start}: {e}")
            return empty

    # ── PASO 2: Documentos.txt ────────────────────────────────────────────────

    def get_paragraph(self, b_par_start: int, b_par_len: int, window: int = 500) -> str:
        """
        Lee el párrafo de contexto de Documentos.txt usando los offsets del párrafo
        — igual que ParrafosFileManagement.cs (con margen ADDITIONAL_BYTES = 500).

        b_par_start / b_par_len : offsets obtenidos de Frases.txt (o de la metadata del chunk).
        window                  : bytes adicionales de margen a izquierda y derecha.
        """
        if not self.documentos_path.exists() or b_par_len == 0:
            return ""

        try:
            first = max(0, b_par_start - window)
            size  = b_par_len + window * 2

            with open(self.documentos_path, "rb") as f:
                f.seek(first)
                raw = f.read(size)

            # Decodificar con fallback
            for enc in (ENCODING, "latin1", "cp1252"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return ""

            # Separar por el delimitador de documento ('§') igual que GetOnlyOneDocument
            if "§" in text:
                # Nos quedamos solo con el fragmento que contiene los bytes centrales
                parts = text.split("§")
                # El fragmento central está en la parte que ocupa la mitad del array
                text = parts[len(parts) // 2]

            return text.strip()

        except Exception as e:
            print(f"[ByteReader] Error leyendo Documentos.txt en offset {b_par_start}: {e}")
            return ""

    # ── Alias de compatibilidad (ingestion.py antiguo) ────────────────────────

    def get_text_by_offsets(self, b_start: int, b_len: int) -> str:
        """
        Alias para leer directamente de Documentos.txt.
        Mantenido por compatibilidad; en el flujo POS correcto usar
        get_sentence_and_paragraph_offsets() + get_paragraph().
        """
        if not self.documentos_path.exists():
            return ""
        try:
            with open(self.documentos_path, "rb") as f:
                f.seek(b_start)
                raw = f.read(b_len)
            return raw.decode(ENCODING, errors="ignore").strip()
        except Exception as e:
            print(f"[ByteReader] Error leyendo documentos.txt en offset {b_start}: {e}")
            return ""
