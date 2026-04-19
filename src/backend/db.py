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


import re


def reconstruct_text(palabras: list[dict]) -> str:
    """Une las palabras en orden de posición y limpia puntuación."""
    if not palabras:
        return ""

    # Ordenar por idFrase y posición
    tokens = sorted(palabras, key=lambda p: (p["idFrase"], p["posElementoFrase"]))

    # Reconstrucción básica
    text = " ".join(p["palabra"] for p in tokens if p.get("palabra"))

    if not text:
        return ""

    # Limpieza de espacios antes de signos de puntuación (e.g. "hola ." -> "hola.")
    text = re.sub(r"\s+([,.?!:;])", r"\1", text)

    # Capitalizar primera letra
    text = text[0].upper() + text[1:] if len(text) > 0 else text

    # Heurística: Si no termina en puntuación, añadir punto.
    if text[-1] not in ".?!":
        text += "."

    return text


def get_context_around_frase(id_frase: int, window: int = 5) -> str:
    """
    Obtiene el texto de las frases que rodean a una frase central.
    Utilizado para expandir el contexto que ve el LLM y lo que se muestra en el UI.
    """
    with get_connection() as conn, get_cursor(conn) as cur:
        # 1. Obtener idDocumento
        cur.execute("SELECT idDocumento FROM frases WHERE idFrases = %s", (id_frase,))
        row = cur.fetchone()
        if not row:
            return ""
        id_doc = row["idDocumento"]

        # 2. Buscar IDs de frases en el rango (ventana)
        # Aseguramos que solo cogemos frases del mismo documento
        sql = """
            SELECT idFrases FROM frases 
            WHERE idDocumento = %s AND idFrases BETWEEN %s AND %s
            ORDER BY idFrases ASC
        """
        cur.execute(sql, (id_doc, id_frase - window, id_frase + window))
        ids = [r["idFrases"] for r in cur.fetchall()]

    if not ids:
        return ""

    # 3. Obtener palabras de todas esas frases y reconstruir
    pals_map = get_palabras_por_frases_batch(ids)
    all_words = []
    # Los IDs ya vienen ordenados por la query SQL
    for fid in ids:
        all_words.extend(pals_map.get(fid, []))

    return reconstruct_text(all_words)


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
    Versión batch robusta: recupera palabras en bloques de 500 para evitar
    el error de 'too many SQL variables'.
    """
    if not ids_frases:
        return {}

    result: dict[int, list[dict]] = {}
    batch_size = 500

    for i in range(0, len(ids_frases), batch_size):
        chunk = ids_frases[i : i + batch_size]
        placeholders = ", ".join(["%s"] * len(chunk))
        sql = f"""
            SELECT idFrase, palabra, lema, categoria, posElementoFrase
            FROM palabras
            WHERE idFrase IN ({placeholders})
            ORDER BY idFrase ASC, posElementoFrase ASC
        """
        with get_connection() as conn, get_cursor(conn) as cur:
            cur.execute(sql, chunk)
            rows = [_fix_encoding(r) for r in cur.fetchall()]

        for row in rows:
            fid = row["idFrase"] # type: ignore[index]
            result.setdefault(fid, []).append(row) # type: ignore[assignment]

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
    """Búsqueda léxica clásica (usada por compatibilidad)."""
    # Mapeamos a la nueva función para centralizar lógica
    from backend.query_analyzer import SearchPlan
    plan = SearchPlan(must_have=lemas, intent="hybrid")
    return lexical_search_advanced(plan, filtros, top_k)


def lexical_search_advanced(
    plan: 'SearchPlan',
    filtros: dict | None = None,
    top_k: int = 40,
) -> list[dict]:
    """
    Búsqueda léxica avanzada que soporta:
    1. Conceptos Semánticos: Búsqueda por lemas (con expansión previa).
    2. Literales: Búsqueda exacta en columna 'palabra'.
    3. Secuenciales: Búsqueda matemática por posición (N-gramas parlamentarios).
    """
    if not any([plan.semantic_concepts, plan.literal_terms, plan.sequential_phrases, plan.must_have]):
        return []

    # 1. Preparar términos básicos
    semantic_terms = [t.lower() for t in (plan.semantic_concepts + plan.must_have + plan.entities)]
    literal_terms = [t.lower() for t in plan.literal_terms]
    
    doc_clauses = []
    doc_params = []
    if filtros:
        if leg := filtros.get("legislatura"):
            doc_clauses.append("d.legislatura = %s")
            doc_params.append(leg)
        if ns := filtros.get("num_sesion"):
            doc_clauses.append("d.numSesion = %s")
            doc_params.append(int(ns))
    where_doc = "AND " + " AND ".join(doc_clauses) if doc_clauses else ""

    results_map = {} # id_frase -> dict con score y datos
    
    with get_connection() as conn, get_cursor(conn) as cur:
        # --- A. Búsqueda SEMÁNTICA (Lemas) y LITERAL (Palabras) ---
        if semantic_terms or literal_terms:
            clauses = []
            params = []
            if semantic_terms:
                ph = ", ".join(["%s"] * len(semantic_terms))
                clauses.append(f"LOWER(p.lema) IN ({ph})")
                params.extend(semantic_terms)
            if literal_terms:
                ph = ", ".join(["%s"] * len(literal_terms))
                clauses.append(f"LOWER(p.palabra) IN ({ph})")
                params.extend(literal_terms)
            
            where_words = " OR ".join(clauses)
            sql_words = f"""
                SELECT f.idFrases, f.orador, f.idDocumento, d.legislatura, d.fecha, d.numSesion,
                       SUM(CASE 
                           WHEN p.categoria BETWEEN 3000 AND 3999 THEN 5 
                           WHEN p.categoria BETWEEN 1000 AND 1999 THEN 3 
                           ELSE 1 END) as score
                FROM palabras p
                JOIN frases f ON p.idFrase = f.idFrases
                JOIN documentos d ON f.idDocumento = d.idDocumento
                WHERE ({where_words}) {where_doc}
                GROUP BY f.idFrases
            """
            cur.execute(sql_words, params + doc_params)
            for row in cur.fetchall():
                fixed = _fix_encoding(row)
                if fixed:
                    results_map[fixed["id_frase" if "id_frase" in fixed else "idFrases"]] = fixed

        # --- B. Búsqueda SECUENCIAL (Orden matemático) ---
        for phrase in plan.sequential_phrases:
            words = re.findall(r"\w+", phrase.lower())
            if len(words) < 2: continue
            
            # Construimos un JOIN dinámico: p1 JOIN p2 ON p2.pos = p1.pos + 1 ...
            joins = []
            wheres = []
            phrase_params = []
            for i, word in enumerate(words):
                alias = f"p{i+1}"
                if i == 0:
                    joins.append(f"palabras {alias}")
                else:
                    prev_alias = f"p{i}"
                    joins.append(f"JOIN palabras {alias} ON {alias}.idFrase = {prev_alias}.idFrase AND {alias}.posElementoFrase = {prev_alias}.posElementoFrase + 1")
                wheres.append(f"LOWER({alias}.palabra) = %s")
                phrase_params.append(word)
            
            sql_seq = f"""
                SELECT DISTINCT p1.idFrase as idPhr
                FROM {" ".join(joins)}
                WHERE {" AND ".join(wheres)}
            """
            cur.execute(sql_seq, phrase_params)
            seq_ids = [r["idPhr"] for r in cur.fetchall()]
            
            if seq_ids:
                ph_ids = ", ".join(["%s"] * len(seq_ids))
                sql_data = f"""
                    SELECT f.idFrases, f.orador, f.idDocumento, d.legislatura, d.fecha, d.numSesion
                    FROM frases f
                    JOIN documentos d ON f.idDocumento = d.idDocumento
                    WHERE f.idFrases IN ({ph_ids}) {where_doc}
                """
                cur.execute(sql_data, seq_ids + doc_params)
                for row in cur.fetchall():
                    fixed = _fix_encoding(row)
                    if not fixed: continue
                    fid = fixed["idFrases"]
                    if fid in results_map:
                        results_map[fid]["score"] += 100 # Super bonus por frase exacta
                    else:
                        fixed["score"] = 120 # Base alta para frases exactas
                        results_map[fid] = fixed

    # 5. Finalizar y ordenar
    final_list = list(results_map.values())
    for item in final_list:
        # Normalizar nombres de llaves
        if "idFrases" in item: item["id_frase"] = item.pop("idFrases")
        if "idDocumento" in item: item["id_documento"] = item.pop("idDocumento")
        if "numSesion" in item: item["num_sesion"] = item.pop("numSesion")

    final_list.sort(key=lambda x: x.get("score", 0), reverse=True)
    return final_list[:top_k]
