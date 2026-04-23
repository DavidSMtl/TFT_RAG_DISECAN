"""
ingestion.py — Pipeline de ingestión simplificado: MySQL -> Bytes -> ChromaDB.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from itertools import islice
from typing import Generator
from backend.chroma_store import count_chunks, upsert_chunks
from backend.db import get_documentos, get_frases_por_documento
from backend.byte_reader import ByteTextReader
from backend.embedder import embed_passages

UPSERT_BATCH = 32
MIN_WORDS = 3

@dataclass
class Chunk:
    texto: str
    orador: str
    id_documento: int
    legislatura: str
    fecha: str
    num_sesion: int
    id_frase_inicio: int
    id_frase_fin: int
    pdf_file: str = ""
    chunk_id: str = ""

    def __post_init__(self):
        if not self.chunk_id:
            self.chunk_id = f"c_{self.id_documento}_{self.id_frase_inicio}"

    def to_metadata(self) -> dict:
        return {
            "id_chunk": self.chunk_id,
            "orador": self.orador or "DESCONOCIDO",
            "id_documento": self.id_documento,
            "legislatura": self.legislatura or "",
            "fecha": self.fecha or "",
            "num_sesion": self.num_sesion or 0,
            "id_frase_inicio": self.id_frase_inicio,
            "id_frase_fin": self.id_frase_fin,
            "pdf_file": self.pdf_file or "",
            "source": "disecan_mysql"
        }


def _create_chunks_from_paragraphs(doc: dict, phrases: list[dict]) -> list[Chunk]:
    chunks, reader, seen_offsets = [], ByteTextReader(), set()
    for f in phrases:
        b_start, b_len = f.get("ByteInicioFrase"), f.get("ByteLongFrase")
        if b_start is None or b_len is None: continue
        if (b_start, b_len) in seen_offsets: continue
        seen_offsets.add((b_start, b_len))
        text = reader.get_text_by_offsets(b_start, b_len)
        if not text or len(text.split()) < MIN_WORDS: continue
        chunks.append(Chunk(
            texto=text, orador=(f.get("orador") or "DESCONOCIDO").strip(),
            id_documento=doc["idDocumento"], legislatura=doc.get("legislatura") or "",
            fecha=str(doc.get("fecha") or ""), num_sesion=doc.get("numSesion") or 0,
            id_frase_inicio=f["idFrases"], id_frase_fin=f["idFrases"],
            pdf_file=doc.get("nombreFicheroPDF", "")
        ))
    return chunks

def _batched(iterable: list, n: int) -> Generator[list, None, None]:
    it = iter(iterable)
    while batch := list(islice(it, n)): yield batch

def run_ingestion(filtros: dict | None = None, force: bool = False, verbose: bool = True) -> int:
    existing = count_chunks()
    if existing > 0 and not force:
        print(f"[Ingestion] Ya hay {existing} chunks. Usa force=True.")
        return existing
    documentos = get_documentos(filtros or {})
    if not documentos: return 0
    total_chunks = 0
    for doc in documentos:
        frases = get_frases_por_documento(doc["idDocumento"])
        if not frases: continue
        chunks = _create_chunks_from_paragraphs(doc, frases)
        for batch in _batched(chunks, UPSERT_BATCH):
            textos = [c.texto for c in batch]
            upsert_chunks([c.chunk_id for c in batch], embed_passages(textos), textos, [c.to_metadata() for c in batch])
            total_chunks += len(batch)
        if verbose: print(f"[*] Doc {doc['idDocumento']}: {len(chunks)} párrafos.")
    return total_chunks
