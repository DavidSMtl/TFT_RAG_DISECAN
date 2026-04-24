"""
db.py — Conector MySQL para la BD DiSeCan (Versión Simplificada).
"""
from __future__ import annotations
import os
import re
from contextlib import contextmanager
from typing import Generator
import mysql.connector
from dotenv import load_dotenv
from mysql.connector import MySQLConnection
from mysql.connector.cursor import MySQLCursor
from backend.byte_reader import ByteTextReader

CAT_CODES = {
    "sustantivo": 1000, "adjetivo": 1100, "adverbio": 1200, "verbo": 3000,
    "artículo": 1700, "pronombre": 1400, "preposición": 1600, "conjunción": 1500
}

load_dotenv()

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

@contextmanager
def get_connection() -> Generator[MySQLConnection, None, None]:
    conn: MySQLConnection = mysql.connector.connect(**_DB_CONFIG)
    try:
        yield conn
    finally:
        conn.close()

@contextmanager
def get_cursor(conn: MySQLConnection) -> Generator[MySQLCursor, None, None]:
    cursor: MySQLCursor = conn.cursor(dictionary=True, buffered=True)
    try:
        yield cursor
    finally:
        cursor.close()

def get_paragraph_for_frase(id_frase: int) -> str:
    """Extrae el párrafo físico usando offsets de MySQL."""
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute("SELECT ByteInicioFrase, ByteLongFrase FROM frases WHERE idFrases = %s", (id_frase,))
        row = cur.fetchone()
        if not row: return ""
    return ByteTextReader().get_text_by_offsets(row["ByteInicioFrase"], row["ByteLongFrase"])

def get_documentos(filtros: dict | None = None) -> list[dict]:
    filtros = filtros or {}
    clauses, params = [], []
    if leg := filtros.get("legislatura"):
        clauses.append("legislatura = %s"); params.append(leg)
    if f_desde := filtros.get("fecha_desde"):
        clauses.append("fecha >= %s"); params.append(f_desde)
    if f_hasta := filtros.get("fecha_hasta"):
        clauses.append("fecha <= %s"); params.append(f_hasta)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"SELECT * FROM documentos {where} ORDER BY fecha ASC"
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql, params)
        return cur.fetchall()

def get_legislaturas() -> list[str]:
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute("SELECT DISTINCT legislatura FROM documentos WHERE legislatura IS NOT NULL ORDER BY legislatura")
        return [r["legislatura"] for r in cur.fetchall()]

def get_frases_por_documento(id_documento: int) -> list[dict]:
    sql = "SELECT idFrases, orador, ByteInicioFrase, ByteLongFrase FROM frases WHERE idDocumento = %s ORDER BY idFrases ASC"
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql, (id_documento,))
        return cur.fetchall()

def get_ids_documentos_por_filtros(filtros: dict) -> list[int] | None:
    docs = get_documentos(filtros)
    if not docs: return []
    if not filtros.get("legislatura"): return None
    return [d["idDocumento"] for d in docs]

def linguistic_search(terminos: list[str], top_k: int = 40) -> list[dict]:
    """
    Búsqueda léxica optimizada. 
    1. Fragmenta frases en palabras.
    2. Filtra palabras vacías.
    3. Busca frases que contengan la mayor cantidad de esos lemas.
    """
    if not terminos: return []

    # 1. Extraer palabras individuales y limpiar
    palabras_busqueda = []
    stopwords = {"de", "la", "el", "en", "y", "a", "los", "las", "un", "una", "por", "con", "no", "su", "para", "es"}
    
    for t in terminos:
        # Dividir si es una frase y limpiar caracteres raros
        parts = re.findall(r'\w+', t.lower())
        palabras_busqueda.extend([p for p in parts if p not in stopwords and len(p) > 2])
    
    # Eliminar duplicados y limitar para no matar la DB
    palabras_busqueda = list(set(palabras_busqueda))[:8]
    
    if not palabras_busqueda:
        return []

    # 2. Construir query de "Best Match" (cuantos más lemas coincidan, mejor)
    placeholders = ", ".join(["%s"] * len(palabras_busqueda))
    
    sql = f"""
        SELECT f.idFrases as id_frase, f.orador, f.idDocumento as id_documento, 
               COUNT(DISTINCT p.lema) as score
        FROM palabras p
        JOIN frases f ON p.idFrase = f.idFrases
        WHERE LOWER(p.lema) IN ({placeholders})
        GROUP BY f.idFrases
        HAVING score >= 1
        ORDER BY score DESC, f.idFrases ASC
        LIMIT %s
    """
    
    params = palabras_busqueda + [top_k]
    
    try:
        with get_connection() as conn, get_cursor(conn) as cur:
            cur.execute(sql, params)
            results = cur.fetchall()
            # Normalizar score (0.0 a 1.0) basado en cuántos lemas de la consulta se encontraron
            for r in results:
                r["score"] = r["score"] / len(palabras_busqueda)
            return results
    except Exception as e:
        print(f"[DB] Error en linguistic_search: {e}")
        return []
