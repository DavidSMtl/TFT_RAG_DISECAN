"""
ingestion.py — Pipeline de ingestión: MySQL → Chunks semánticos → ChromaDB.

Lógica de chunking:
  - Chunk = todas las frases CONSECUTIVAS del mismo orador en el mismo documento
  - El límite natural es el cambio de orador (turno de palabra), no el nº de tokens
  - El texto se reconstruye concatenando las palabras en orden (posElementoFrase)

Uso (script independiente):
    uv run python src/ingestion_run.py

O desde Python:
    from backend.ingestion import run_ingestion
    run_ingestion()
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from itertools import islice
from typing import Generator

from backend.chroma_store import count_chunks, upsert_chunks
from backend.db import (
    get_documentos,
    get_frases_por_documento,
    get_palabras_por_frases_batch,
    reconstruct_text,
)
from backend.embedder import embed_passages

# ── Configuración ──────────────────────────────────────────────────────────────

UPSERT_BATCH = 32   # Chunks por lote de embedding + upsert
MIN_WORDS = 3       # Descartar chunks de menos de N palabras
CHUNK_MAX_WORDS = 400 # Tamaño objetivo de un fragmento (en palabras acumuladas)


# ── Estructuras ────────────────────────────────────────────────────────────────


@dataclass
class Chunk:
    """Representa un fragmento de texto (párrafo) compuesto por frases completas."""
    texto: str
    orador: str
    id_documento: int
    legislatura: str
    fecha: str           # ISO: "YYYY-MM-DD"
    num_sesion: int
    id_frase_inicio: int
    id_frase_fin: int
    num_frases: int
    frases_data: str = "" # JSON string: { "idFrase": "Reconstructed text" }
    pdf_file: str = ""
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_metadata(self) -> dict:
        return {
            "orador": self.orador or "",
            "id_documento": self.id_documento,
            "legislatura": self.legislatura or "",
            "fecha": self.fecha,
            "num_sesion": self.num_sesion,
            "id_frase_inicio": self.id_frase_inicio,
            "id_frase_fin": self.id_frase_fin,
            "num_frases": self.num_frases,
            "pdf_file": self.pdf_file,
            "frases_data": self.frases_data
        }


# Lógica de reconstrucción de texto


import json


# Lógica de chunking




def _chunks_de_documento(
    doc: dict, phrases: list[dict], words_per_phrase: dict[int, list[dict]]
) -> list[Chunk]:
    """
    Agrupa frases consecutivas del mismo orador en un solo chunk (Párrafo).
    Guarda un mapa idFrase -> texto en los metadatos.
    """
    chunks: list[Chunk] = []
    if not phrases:
        return []

    current_speaker = None
    current_frases: list[dict] = []
    current_words_count = 0

    def flush_chunk():
        nonlocal current_frases, current_speaker, current_words_count
        if not current_frases:
            return

        all_words_in_chunk = []
        frases_map = {}
        
        for f in current_frases:
            fid = f["idFrases"]
            pals = words_per_phrase.get(fid, [])
            if not pals: continue
            
            # Reconstruir frase individual (con puntuación heurística de db.reconstruct_text)
            f_text = reconstruct_text(pals)
            frases_map[str(fid)] = f_text
            all_words_in_chunk.extend(pals)

        if not all_words_in_chunk:
            return

        full_text = reconstruct_text(all_words_in_chunk)
        
        # Filtro mínimo de calidad
        if len(full_text.split()) < MIN_WORDS:
            return

        chunks.append(Chunk(
            texto=full_text,
            orador=(current_speaker or "DESCONOCIDO").strip(),
            id_documento=doc["idDocumento"],
            legislatura=doc.get("legislatura") or "",
            fecha=str(doc.get("fecha") or ""),
            num_sesion=doc.get("numSesion") or 0,
            id_frase_inicio=current_frases[0]["idFrases"],
            id_frase_fin=current_frases[-1]["idFrases"],
            num_frases=len(current_frases),
            frases_data=json.dumps(frases_map),
            pdf_file=doc.get("nombreFicheroPDF", "")
        ))

    for f in phrases:
        speaker = (f.get("orador") or "DESCONOCIDO").strip()
        fid = f["idFrases"]
        words_f = words_per_phrase.get(fid, [])
        word_count = len(words_f)

        if current_speaker is None:
            current_speaker = speaker

        # Lógica de agrupación: mismo orador Y no exceder límite de palabras
        if speaker == current_speaker and current_words_count + word_count <= CHUNK_MAX_WORDS:
            current_frases.append(f)
            current_words_count += word_count
        else:
            flush_chunk()
            current_speaker = speaker
            current_frases = [f]
            current_words_count = word_count

    flush_chunk() # Último chunk
    return chunks


# ── Batching helper ────────────────────────────────────────────────────────────


def _batched(iterable: list, n: int) -> Generator[list, None, None]:
    """Divide una lista en lotes de tamaño n."""
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch


# ── Pipeline principal ─────────────────────────────────────────────────────────


def run_ingestion(
    filtros: dict | None = None,
    force: bool = False,
    verbose: bool = True,
) -> int:
    """
    Ejecuta el pipeline completo de ingestión.

    Args:
        filtros : filtros de documentos (legislatura, fecha_desde, etc.)
        force   : si False y ya hay chunks en ChromaDB, no re-ingesta
        verbose : imprime progreso

    Returns:
        Número total de chunks insertados/actualizados
    """
    # Comprobar si ya hay datos
    existing = count_chunks()
    if existing > 0 and not force:
        print(f"[Ingestion] Ya hay {existing} chunks en ChromaDB. Usa force=True para re-ingestar.")
        return existing

    documentos = get_documentos(filtros or {})
    if not documentos:
        print("[Ingestion] No se encontraron documentos con los filtros dados.")
        return 0

    total_chunks = 0
    total_docs = len(documentos)

    for doc_idx, doc in enumerate(documentos, 1):
        id_doc = doc["idDocumento"]
        if verbose:
            print(f"[Ingestion] Documento {doc_idx}/{total_docs} (id={id_doc}, sesión={doc.get('numSesion')})...")

        # 1. Obtener frases del documento
        frases = get_frases_por_documento(id_doc)
        if not frases:
            continue

        # 2. Obtener palabras en batch (una sola query SQL)
        ids_frases = [f["idFrases"] for f in frases]
        palabras_por_frase = get_palabras_por_frases_batch(ids_frases)

        # 3. Generar chunks (turnos completos del orador)
        chunks = _chunks_de_documento(doc, frases, palabras_por_frase)
        if not chunks:
            continue

        # 4. Procesar en lotes: embed + upsert
        for batch in _batched(chunks, UPSERT_BATCH):
            textos = [c.texto for c in batch]
            embeddings = embed_passages(textos)

            upsert_chunks(
                ids=[c.chunk_id for c in batch],
                embeddings=embeddings,
                documents=textos,
                metadatas=[c.to_metadata() for c in batch],
            )
            total_chunks += len(batch)

        if verbose:
            print(f"  -> {len(chunks)} chunks generados (total acumulado: {total_chunks})")

    print(f"\n[Ingestion] Completado. {total_chunks} chunks en ChromaDB.")
    return total_chunks
