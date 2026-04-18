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


def _fix_encoding(row: dict | None) -> dict | None:
    if not row:
        return row
    fixed = {}
    for k, v in row.items():
        if isinstance(v, str):
            try:
                fixed[k] = v.encode('cp1252').decode('utf-8')
            except Exception:
                fixed[k] = v
        else:
            fixed[k] = v
    return fixed


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
        return [_fix_encoding(r) for r in cur.fetchall()]  # type: ignore[misc]


def get_legislaturas() -> list[str]:
    """Devuelve las legislaturas distintas disponibles (para filtros UI)."""
    sql = "SELECT DISTINCT legislatura FROM documentos ORDER BY legislatura"
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql)
        rows = [_fix_encoding(r) for r in cur.fetchall()]
    return [r["legislatura"] for r in rows if r and r.get("legislatura")]  # type: ignore[index]


def get_oradores() -> list[str]:
    """Devuelve los oradores distintos (para filtros UI). Puede ser lento sin índice."""
    sql = "SELECT DISTINCT orador FROM frases WHERE orador IS NOT NULL ORDER BY orador LIMIT 2000"
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql)
        rows = [_fix_encoding(r) for r in cur.fetchall()]
    return [r["orador"] for r in rows if r and r.get("orador")]  # type: ignore[index]


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
        return [_fix_encoding(r) for r in cur.fetchall()]  # type: ignore[misc]


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
        return [_fix_encoding(r) for r in cur.fetchall()]  # type: ignore[misc]


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
        rows = [_fix_encoding(r) for r in cur.fetchall()]

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


# ── Búsqueda léxica por lemas (DiSeCan) ───────────────────────────────────────


def lexical_search_chunks(
    lemas: list[str],
    filtros: dict | None = None,
    top_k: int = 40,
) -> list[dict]:
    """
    Búsqueda léxica al estilo DiSeCan: busca lemas exactos en la tabla `palabras`
    y devuelve los grupos (id_documento, id_frase_inicio, id_frase_fin) con mayor
    número de coincidencias. Esto permite mapear resultados SQL → chunk de Chroma.

    Args:
        lemas   : lista de lemas normalizados (ej: ["universidad", "presupuesto"])
        filtros : dict con 'legislatura', 'num_sesion', etc. (optional)
        top_k   : máximo de resultados

    Returns:
        lista de dicts con:
            id_documento, id_frase, orador, fecha, legislatura, num_sesion,
            n_matches (nº de lemas encontrados en frases cercanas)
    """
    if not lemas:
        return []

    # Normalizar lemas a minúsculas
    lemas_lower = [l.lower() for l in lemas if l.strip()]
    if not lemas_lower:
        return []

    placeholders = ", ".join(["%s"] * len(lemas_lower))

    # Filtros de documentos opcionales
    doc_clauses: list[str] = []
    doc_params: list[object] = []
    if filtros:
        if leg := filtros.get("legislatura"):
            doc_clauses.append("d.legislatura = %s")
            doc_params.append(leg)
        if ns := filtros.get("num_sesion"):
            doc_clauses.append("d.numSesion = %s")
            doc_params.append(int(ns))

    where_doc = "AND " + " AND ".join(doc_clauses) if doc_clauses else ""

    # La query busca frases donde aparecen los lemas buscados,
    # agrupa por frase y cuenta cuántos lemas distintos aparecen.
    # ORDER BY n_matches DESC garantiza que las frases más relevantes van primero.
    sql = f"""
        SELECT
            f.idFrases      AS id_frase,
            f.orador        AS orador,
            f.idDocumento   AS id_documento,
            d.legislatura   AS legislatura,
            d.fecha         AS fecha,
            d.numSesion     AS num_sesion,
            COUNT(DISTINCT p.lema) AS n_matches
        FROM palabras p
        JOIN frases f   ON p.idFrase = f.idFrases
        JOIN documentos d ON f.idDocumento = d.idDocumento
        WHERE LOWER(p.lema) IN ({placeholders})
        {where_doc}
        GROUP BY f.idFrases, f.orador, f.idDocumento, d.legislatura, d.fecha, d.numSesion
        ORDER BY n_matches DESC, f.idFrases ASC
        LIMIT %s
    """
    params = lemas_lower + doc_params + [top_k * 4]  # traer más para filtrar duplicados

    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql, params)
        rows = [_fix_encoding(r) for r in cur.fetchall()]

    return rows  # type: ignore[return-value]
