"""
db.py — Conector MySQL para la BD DiSeCan.

Uso:
    from backend.db import get_connection, get_documentos, get_palabras_por_frase
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

import mysql.connector
from dotenv import load_dotenv
from mysql.connector import MySQLConnection
from mysql.connector.cursor import MySQLCursor

load_dotenv()  # Lee .env desde el directorio de trabajo

# ── Configuración ──────────────────────────────────────────────────────────────

_DB_CONFIG: dict[str, object] = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "database": os.getenv("DB_NAME", "disecan"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASS", ""),
    "charset": "utf8mb4",
    "use_unicode": True,
    "autocommit": True,
}


# ── Conexión ───────────────────────────────────────────────────────────────────


@contextmanager
def get_connection() -> Generator[MySQLConnection, None, None]:
    """Context manager que abre y cierra la conexión automáticamente."""
    conn: MySQLConnection = mysql.connector.connect(**_DB_CONFIG)  # type: ignore[arg-type]
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_cursor(conn: MySQLConnection) -> Generator[MySQLCursor, None, None]:
    """Context manager para cursores (dictionary=True por defecto)."""
    cursor: MySQLCursor = conn.cursor(dictionary=True)
    try:
        yield cursor
    finally:
        cursor.close()


# ── Consultas de metadatos ─────────────────────────────────────────────────────


def get_documentos(filtros: dict | None = None) -> list[dict]:
    """
    Devuelve la lista de documentos, opcionalmente filtrada.

    Filtros soportados (todos opcionales):
        legislatura : str   → ej. "X"
        orador      : str   → coincidencia parcial en frases.orador
        fecha_desde : str   → "YYYY-MM-DD"
        fecha_hasta : str   → "YYYY-MM-DD"
        num_sesion  : int
    """
    filtros = filtros or {}

    clauses: list[str] = []
    params: list[object] = []

    if leg := filtros.get("legislatura"):
        clauses.append("d.legislatura = %s")
        params.append(leg)
    if fd := filtros.get("fecha_desde"):
        clauses.append("d.fecha >= %s")
        params.append(fd)
    if fh := filtros.get("fecha_hasta"):
        clauses.append("d.fecha <= %s")
        params.append(fh)
    if ns := filtros.get("num_sesion"):
        clauses.append("d.numSesion = %s")
        params.append(int(ns))

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"""
        SELECT
            d.idDocumento,
            d.nombreFicheroPDF,
            d.legislatura,
            d.fecha,
            d.numSesion,
            d.presidente
        FROM documentos d
        {where}
        ORDER BY d.fecha ASC
    """

    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql, params)
        return cur.fetchall()  # type: ignore[return-value]


def get_legislaturas() -> list[str]:
    """Devuelve las legislaturas distintas disponibles (para filtros UI)."""
    sql = "SELECT DISTINCT legislatura FROM documentos ORDER BY legislatura"
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return [r["legislatura"] for r in rows if r["legislatura"]]  # type: ignore[index]


def get_oradores() -> list[str]:
    """Devuelve los oradores distintos (para filtros UI). Puede ser lento sin índice."""
    sql = "SELECT DISTINCT orador FROM frases WHERE orador IS NOT NULL ORDER BY orador LIMIT 2000"
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return [r["orador"] for r in rows]  # type: ignore[index]


# ── Consultas de ingestión ─────────────────────────────────────────────────────


def get_frases_por_documento(id_documento: int) -> list[dict]:
    """
    Devuelve todas las frases de un documento, ordenadas por idFrases.

    Columnas: idFrases, orador, ByteInicioFrase, ByteLongFrase, revisada, metafora
    """
    sql = """
        SELECT
            idFrases,
            orador,
            ByteInicioFrase,
            ByteLongFrase,
            revisada,
            metafora
        FROM frases
        WHERE idDocumento = %s
        ORDER BY idFrases ASC
    """
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql, (id_documento,))
        return cur.fetchall()  # type: ignore[return-value]


def get_palabras_por_frase(id_frase: int) -> list[dict]:
    """
    Devuelve los tokens de una frase ordenados por posición.

    Columnas: palabra, lema, categoria, posElementoFrase
    """
    sql = """
        SELECT
            palabra,
            lema,
            categoria,
            posElementoFrase
        FROM palabras
        WHERE idFrase = %s
        ORDER BY posElementoFrase ASC
    """
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql, (id_frase,))
        return cur.fetchall()  # type: ignore[return-value]


def get_palabras_por_frases_batch(ids_frases: list[int]) -> dict[int, list[dict]]:
    """
    Versión batch: recupera palabras de una lista de frases en UNA sola query.
    Mucho más eficiente para la ingestión masiva.

    Devuelve: { id_frase: [palabras ordenadas] }
    """
    if not ids_frases:
        return {}

    placeholders = ", ".join(["%s"] * len(ids_frases))
    sql = f"""
        SELECT
            idFrase,
            palabra,
            lema,
            categoria,
            posElementoFrase
        FROM palabras
        WHERE idFrase IN ({placeholders})
        ORDER BY idFrase ASC, posElementoFrase ASC
    """
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql, ids_frases)
        rows = cur.fetchall()

    # Agrupar por idFrase
    result: dict[int, list[dict]] = {}
    for row in rows:
        fid = row["idFrase"]  # type: ignore[index]
        result.setdefault(fid, []).append(row)  # type: ignore[assignment]
    return result


def get_ids_documentos_por_filtros(filtros: dict) -> list[int] | None:
    """
    Dado un dict de filtros, devuelve la lista de idDocumento que los cumplen.
    Devuelve None si no hay filtros (= sin restricción, buscar en todo).
    """
    docs = get_documentos(filtros)
    if not docs:
        return []
    # Si no había filtros activos, devolvemos None para indicar "sin restricción"
    _tiene_filtros = any(
        filtros.get(k) for k in ("legislatura", "fecha_desde", "fecha_hasta", "num_sesion")
    )
    if not _tiene_filtros:
        return None
    return [d["idDocumento"] for d in docs]  # type: ignore[index]
