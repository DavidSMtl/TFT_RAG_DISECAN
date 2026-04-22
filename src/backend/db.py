"""
db.py — Conector MySQL para la BD DiSeCan (Versión Simplificada).
"""
from __future__ import annotations
import os
from contextlib import contextmanager
from typing import Generator
import mysql.connector
from dotenv import load_dotenv
from mysql.connector import MySQLConnection
from mysql.connector.cursor import MySQLCursor
from backend.byte_reader import ByteTextReader

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
    cursor: MySQLCursor = conn.cursor(dictionary=True)
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

def lexical_search_chunks(lemas: list[str], filtros: dict | None = None, top_k: int = 40) -> list[dict]:
    if not lemas: return []
    ph = ", ".join(["%s"] * len(lemas))
    sql = f"""
        SELECT f.idFrases as id_frase, f.orador, f.idDocumento as id_documento, d.legislatura, d.fecha, COUNT(*) as score
        FROM palabras p
        JOIN frases f ON p.idFrase = f.idFrases
        JOIN documentos d ON f.idDocumento = d.idDocumento
        WHERE LOWER(p.lema) IN ({ph})
        GROUP BY f.idFrases ORDER BY score DESC LIMIT %s
    """
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql, [L.lower() for L in lemas] + [top_k])
        return cur.fetchall()
