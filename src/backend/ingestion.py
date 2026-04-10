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
)
from backend.embedder import embed_passages

# ── Configuración ──────────────────────────────────────────────────────────────

UPSERT_BATCH = 32   # Chunks por lote de embedding + upsert (ajustar según RAM)
MIN_WORDS = 3       # Descartar chunks de menos de N palabras (ruido)


# ── Estructuras ────────────────────────────────────────────────────────────────


@dataclass
class Chunk:
    """Representa el turno completo de un orador en un documento."""
    texto: str
    orador: str
    id_documento: int
    legislatura: str
    fecha: str           # ISO: "YYYY-MM-DD"
    num_sesion: int
    id_frase_inicio: int
    id_frase_fin: int
    num_frases: int
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
        }


# Lógica de reconstrucción de texto


def _reconstruir_texto(palabras: list[dict]) -> str:
    """
    Une las palabras en orden de posición para obtener el texto natural.
    Las palabras vienen con: palabra, lema, categoria, posElementoFrase
    """
    tokens = sorted(palabras, key=lambda p: p["posElementoFrase"])
    return " ".join(p["palabra"] for p in tokens if p.get("palabra"))


# Lógica de chunking


def _agrupar_turnos(frases: list[dict]) -> list[tuple[str, list[dict]]]:
    """
    Agrupa frases consecutivas por orador.
    Devuelve lista de (orador, [frases_del_turno]).

    Consideraciones:
    - Si orador es None/vacío, se agrupa bajo "DESCONOCIDO"
    - Dos frases seguidas del mismo orador = mismo turno (aunque haya salto de idFrases)
    """
    turnos: list[tuple[str, list[dict]]] = []
    orador_actual: str | None = None
    grupo_actual: list[dict] = []

    for frase in frases:
        orador = (frase.get("orador") or "DESCONOCIDO").strip()
        if orador == orador_actual:
            grupo_actual.append(frase)
        else:
            if grupo_actual:
                turnos.append((orador_actual or "DESCONOCIDO", grupo_actual))
            orador_actual = orador
            grupo_actual = [frase]

    if grupo_actual:
        turnos.append((orador_actual or "DESCONOCIDO", grupo_actual))

    return turnos


def _chunks_de_documento(doc: dict, frases: list[dict], palabras_por_frase: dict[int, list[dict]]) -> list[Chunk]:
    """
    Genera todos los chunks de un documento dado sus frases y palabras.

    Args:
        doc              : fila de documentos (idDocumento, legislatura, fecha, numSesion)
        frases           : frases del documento ordenadas
        palabras_por_frase: {idFrase: [palabras]}
    """
    chunks: list[Chunk] = []
    turnos = _agrupar_turnos(frases)

    for orador, frases_turno in turnos:
        # Reconstruir texto del turno completo
        palabras_turno: list[dict] = []
        for frase in frases_turno:
            palabras_turno.extend(palabras_por_frase.get(frase["idFrases"], []))

        texto = _reconstruir_texto(palabras_turno)

        # Descartar chunks vacíos o de muy pocas palabras
        if len(texto.split()) < MIN_WORDS:
            continue

        chunks.append(
            Chunk(
                texto=texto,
                orador=orador,
                id_documento=doc["idDocumento"],
                legislatura=doc.get("legislatura") or "",
                fecha=str(doc.get("fecha") or ""),
                num_sesion=doc.get("numSesion") or 0,
                id_frase_inicio=frases_turno[0]["idFrases"],
                id_frase_fin=frases_turno[-1]["idFrases"],
                num_frases=len(frases_turno),
            )
        )

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
            print(f"  → {len(chunks)} chunks generados (total acumulado: {total_chunks})")

    print(f"\n[Ingestion] Completado. {total_chunks} chunks en ChromaDB.")
    return total_chunks
