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

def _get_cat_condition(alias: str, cat_name: str) -> str:
    cat_name = cat_name.lower()
    code = CAT_CODES.get(cat_name)
    if not code: return "1=1"
    if code == 3000:
        return f"({alias}.categoria >= 3000 AND {alias}.categoria < 4000)"
    else:
        return f"({alias}.categoria >= {code} AND {alias}.categoria < {code + 100})"

def linguistic_search_pattern(pattern_str: str, top_k: int = 40) -> list[dict]:
    parts = pattern_str.split()
    tokens = []
    dist_next = 1
    
    for p in parts:
        if p.isdigit():
            dist_next = int(p) + 1
            continue
            
        token = {"dist_prev": dist_next}
        dist_next = 1
        
        p_lower = p.lower()
        if p_lower.startswith("<") and p_lower.endswith(">"):
            token["type"] = "cat"
            token["val"] = p_lower[1:-1]
        elif p_lower.startswith("[") and p_lower.endswith("]"):
            inner = p_lower[1:-1]
            if ":" in inner:
                lema, cat = inner.split(":", 1)
                token["type"] = "lema_cat"
                token["lema"] = lema
                token["cat"] = cat
            else:
                token["type"] = "lema"
                token["val"] = inner
        elif ":" in p_lower and not p_lower.startswith('"'):
            palabra, cat = p_lower.split(":", 1)
            token["type"] = "palabra_cat"
            token["palabra"] = palabra
            token["cat"] = cat
        elif p.startswith('"') and p.endswith('"'):
            token["type"] = "exact"
            token["val"] = p[1:-1].lower()
        else:
            token["type"] = "lema"
            token["val"] = p_lower
            
        for k in ["val", "lema", "palabra"]:
            if k in token and isinstance(token[k], str) and token[k].endswith("*"):
                token[k] = token[k][:-1] + "%"
                token["type"] += "_like"
                
        tokens.append(token)
        
    if not tokens:
        return []

    joins = []
    wheres = []
    params = []
    
    for i, t in enumerate(tokens):
        alias = f"p{i}"
        if i == 0:
            joins.append(f"FROM palabras {alias}")
        else:
            prev_alias = f"p{i-1}"
            joins.append(f"JOIN palabras {alias} ON {alias}.idFrase = {prev_alias}.idFrase")
            dist = t["dist_prev"]
            wheres.append(f"{alias}.posElementoFrase > {prev_alias}.posElementoFrase")
            wheres.append(f"{alias}.posElementoFrase <= {prev_alias}.posElementoFrase + {dist}")
            
        ttype = t["type"]
        if "cat" == ttype:
            wheres.append(_get_cat_condition(alias, t["val"]))
        elif "lema" == ttype:
            wheres.append(f"{alias}.lema = %s")
            params.append(t["val"])
        elif "lema_like" == ttype:
            wheres.append(f"{alias}.lema LIKE %s")
            params.append(t["val"])
        elif "exact" == ttype:
            wheres.append(f"LOWER({alias}.palabra) = %s")
            params.append(t["val"])
        elif "exact_like" == ttype:
            wheres.append(f"LOWER({alias}.palabra) LIKE %s")
            params.append(t["val"])
        elif "lema_cat" in ttype:
            if "like" in ttype:
                wheres.append(f"{alias}.lema LIKE %s")
            else:
                wheres.append(f"{alias}.lema = %s")
            params.append(t["lema"])
            wheres.append(_get_cat_condition(alias, t["cat"]))
        elif "palabra_cat" in ttype:
            if "like" in ttype:
                wheres.append(f"LOWER({alias}.palabra) LIKE %s")
            else:
                wheres.append(f"LOWER({alias}.palabra) = %s")
            params.append(t["palabra"])
            wheres.append(_get_cat_condition(alias, t["cat"]))

    joins_str = "\n".join(joins)
    wheres_str = " AND ".join(wheres) if wheres else "1=1"
    
    sql = f'''
        SELECT f.idFrases as id_frase, f.orador, f.idDocumento as id_documento, 1.0 as score
        {joins_str}
        JOIN frases f ON p0.idFrase = f.idFrases
        WHERE {wheres_str}
        GROUP BY f.idFrases
        LIMIT %s
    '''
    params.append(top_k)
    
    try:
        with get_connection() as conn, get_cursor(conn) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as e:
        print(f"[DB/Pattern] Error: {e}")
        return []

def linguistic_search(terminos: list[str], top_k: int = 40) -> list[dict]:
    """
    Búsqueda léxica optimizada. 
    1. Fragmenta frases en palabras.
    2. Filtra palabras vacías.
    3. Lematiza los términos de búsqueda usando el servicio de lematización.
    4. Busca frases que contengan la mayor cantidad de esos lemas.
    """
    if not terminos: return []
    
    # 0. Interceptar sintaxis avanzada de DiSeCan
    for t in terminos:
        if any(c in t for c in "[]<>*") or ":" in t:
            return linguistic_search_pattern(t, top_k)

    from backend.lemmatizer import get_lemas

    # 1. Extraer palabras individuales y limpiar
    palabras_raw = []
    stopwords = {"de", "la", "el", "en", "y", "a", "los", "las", "un", "una", "por", "con", "no", "su", "para", "es"}
    
    for t in terminos:
        # Dividir si es una frase y limpiar caracteres raros
        parts = re.findall(r'\w+', t.lower())
        palabras_raw.extend([p for p in parts if p not in stopwords and len(p) > 2])
    
    palabras_raw = list(set(palabras_raw))

    # 2. Lematizar las palabras obtenidas
    palabras_busqueda = []
    for p in palabras_raw:
        lemas_p = get_lemas(p)
        palabras_busqueda.extend(lemas_p)
    
    # Eliminar duplicados y limitar para no sobrecargar la BD
    palabras_busqueda = list(set(palabras_busqueda))[:8]
    
    if not palabras_busqueda:
        return []

    # 3. Construir query de "Best Match" (cuantos más lemas coincidan, mejor)
    placeholders = ", ".join(["%s"] * len(palabras_busqueda))
    
    # Búsqueda insensible a acentos y mayúsculas usando la colación nativa
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
