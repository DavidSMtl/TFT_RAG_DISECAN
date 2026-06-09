"""
db.py — Conector MySQL para la BD DiSeCan.

Implementa la búsqueda lingüística DISECAN fiel al original C# (DatabasePattern.cs),
incluyendo todos los tipos de token:
  - <categoria>          → cat_gramatical
  - [lema]               → flexion_conjugacion
  - [lema:cat]           → flexion_categoria
  - [lema*:cat]          → flexion_comodin_categoria
  - [lema*]              → flexion_comodin
  - palabra:cat          → palabra_categoria
  - palabra*:cat         → palabra_comodin_categoria
  - palabra*             → palabra_comodin
  - palabra              → exacto (lema o palabra exacta)
  - N (número)           → distancia entre tokens
"""
from __future__ import annotations
import os
import re
import logging
from contextlib import contextmanager
from typing import Generator

import mysql.connector
from dotenv import load_dotenv
from mysql.connector import MySQLConnection
from mysql.connector.cursor import MySQLCursor

from backend.byte_reader import ByteTextReader

logger = logging.getLogger("disecan.db")

# ── Códigos de categoría (idénticos a LinguakitCodesAndText.cs) ──────────────
# Cada clave es el nombre normalizado que acepta el usuario.
# Los "generales" (sin subcategoría) tienen un rango de ~7 códigos consecutivos.
CAT_CODES: dict[str, int] = {
    # Categorías generales (rango > code AND < code+7 como en el C#)
    "adjetivo":     1100,
    "adverbio":     1200,
    "artículo":     1700,
    "artículo":     1700,
    "conjunción":   1500,
    "interjección": 1301,
    "preposición":  1600,
    "pronombre":    1400,
    "sustantivo":   1000,
    "verbo":        3000,
    # Categorías específicas (código exacto, igual que en el C#)
    "adjetivo calificativo":        1101,
    "adjetivo posesivo":            1102,
    "adjetivo ordinario":           1103,
    "adverbio general":             1201,
    "adverbio negativo":            1202,
    "artículo determinado":         1701,
    "artículo indeterminado":       1702,
    "determinante":                 2000,
    "determinante artículo":        2001,
    "determinante demostrativo":    2002,
    "determinante indefinido":      2003,
    "determinante posesivo":        2004,
    "determinante interrogativo":   2005,
    "determinante exclamativo":     2006,
    "número":                       4001,
    "preposición latina":           1601,
    "pronombre demostrativo":       1401,
    "pronombre exclamativo":        1402,
    "pronombre indefinido":         1403,
    "pronombre personal":           1404,
    "pronombre relativo":           1405,
    "pronombre interrogativo":      1406,
    "sustantivo común":             1001,
    "sustantivo propio":            1002,
}

# Categorías "generales" — usan rango como en el C#: > code AND < (code+7)
CAT_GENERALES = {
    "adjetivo", "adverbio", "artículo", "conjunción",
    "interjección", "preposición", "pronombre", "sustantivo", "verbo",
}

# Alias cortos que acepta el buscador (mismos que dicCategorias en Default.aspx.cs)
CAT_ALIAS: dict[str, str] = {
    "adj":         "adjetivo",
    "adv":         "adverbio",
    "articulo":    "artículo",
    "art":         "artículo",
    "conjuncion":  "conjunción",
    "conj":        "conjunción",
    "interjeccion":"interjección",
    "interj":      "interjección",
    "preposicion": "preposición",
    "prep":        "preposición",
    "pron":        "pronombre",
    "sust":        "sustantivo",
    "s":           "sustantivo",
    "nombre":      "sustantivo",
    "v":           "verbo",
    # sustantivo común/propio
    "sc":          "sustantivo común",
    "sp":          "sustantivo propio",
}

load_dotenv()

_DB_CONFIG: dict[str, object] = {
    "host":       os.getenv("DB_HOST", "127.0.0.1"),
    "port":       int(os.getenv("DB_PORT", "3306")),
    "database":   os.getenv("DB_NAME", "disecan"),
    "user":       os.getenv("DB_USER", "root"),
    "password":   os.getenv("DB_PASS", ""),
    "charset":    "utf8mb4",
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


# ── Funciones básicas de la BD ────────────────────────────────────────────────

def get_paragraph_for_frase(id_frase: int) -> str:
    """Extrae el párrafo físico usando offsets de MySQL."""
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(
            "SELECT ByteInicioFrase, ByteLongFrase FROM frases WHERE idFrases = %s",
            (id_frase,)
        )
        row = cur.fetchone()
        if not row:
            return ""
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
        cur.execute(
            "SELECT DISTINCT legislatura FROM documentos "
            "WHERE legislatura IS NOT NULL ORDER BY legislatura"
        )
        return [r["legislatura"] for r in cur.fetchall()]


def get_frases_por_documento(id_documento: int) -> list[dict]:
    sql = (
        "SELECT idFrases, orador, ByteInicioFrase, ByteLongFrase "
        "FROM frases WHERE idDocumento = %s ORDER BY idFrases ASC"
    )
    with get_connection() as conn, get_cursor(conn) as cur:
        cur.execute(sql, (id_documento,))
        return cur.fetchall()


def get_ids_documentos_por_filtros(filtros: dict) -> list[int] | None:
    docs = get_documentos(filtros)
    if not docs:
        return []
    if not filtros.get("legislatura"):
        return None
    return [d["idDocumento"] for d in docs]


# ── Helpers internos ──────────────────────────────────────────────────────────

def _normalize_cat(name: str) -> str:
    """Normaliza el nombre de categoría: alias cortos → nombre completo."""
    n = name.lower().strip()
    return CAT_ALIAS.get(n, n)


def _cat_condition(alias: str, cat_name: str, general_range: str = "narrow") -> tuple[str, list]:
    """
    Genera la condición SQL de categoría para el alias dado.
    Fiel al C# DatabasePattern.cs:
      - <cat>           (cat_gramatical sola):      > code  AND < (code + 7)   [general_range='narrow']
      - [lema]:cat      (flexion + categoría):      >= code AND < (code + 99)  [general_range='wide']
      - categorías específicas: = code  (siempre)
    """
    cat = _normalize_cat(cat_name)
    code = CAT_CODES.get(cat)
    if code is None:
        logger.warning(f"[DB] Categoría desconocida: '{cat_name}' → ignorada (1=1)")
        return "1=1", []
    if cat in CAT_GENERALES:
        if general_range == "wide":
            return f"({alias}.categoria >= {code} AND {alias}.categoria < {code + 99})", []
        else:  # narrow (para <cat_gramatical>)
            return f"({alias}.categoria > {code} AND {alias}.categoria < {code + 7})", []
    else:
        return f"({alias}.categoria = {code})", []


# ── Tipos de token (equivalentes a InputTypes del C#) ────────────────────────

def _parse_token(raw: str) -> dict:
    """
    Clasifica un token DISECAN y devuelve un diccionario con:
      type   : uno de los tipos enumerados a continuación
      val    : valor principal (lema, palabra, etc.)
      cat    : nombre de categoría (opcional)
      like   : True si hay wildcard (* → %)

    Tipos posibles:
      cat_gramatical           → <categoria>
      flexion_conjugacion      → [lema]
      flexion_conjugacion_like → [lema*]
      flexion_categoria        → [lema]:cat
      flexion_categoria_like   → [lema*]:cat
      palabra_categoria        → palabra:cat
      palabra_categoria_like   → palabra*:cat
      palabra_comodin          → palabra*
      exacto                   → palabra  (búsqueda por lema = en BD)
    """
    p = raw.strip()
    p_lower = p.lower()

    # ── <categoria> ──────────────────────────────────────────────────────────
    if p_lower.startswith("<") and p_lower.endswith(">"):
        return {"type": "cat_gramatical", "val": p_lower[1:-1]}

    # ── [lema] o [lema*] o [lema]:cat o [lema*]:cat o [lema:cat] ─────────────
    # Soportamos tanto la sintaxis canónica [lema]:cat como la alternativa [lema:cat]
    if p_lower.startswith("["):
        bracket_end = p_lower.find("]")
        if bracket_end == -1:
            return {"type": "exacto", "val": p_lower, "like": False}

        inner = p_lower[1:bracket_end]
        rest = p_lower[bracket_end + 1:]  # vacío o ":cat"

        # Detectar colon dentro de los corchetes: [lema:cat] → lema + cat
        cat = None
        if ":" in inner:
            lema_part, cat_part = inner.split(":", 1)
            inner = lema_part
            cat = cat_part
        elif rest.startswith(":"):
            cat = rest[1:]

        has_wild = "*" in inner or "?" in inner
        inner_sql = inner.replace("*", "%").replace("?", "_")

        if cat:
            ttype = "flexion_categoria_like" if has_wild else "flexion_categoria"
            return {"type": ttype, "val": inner_sql, "cat": cat, "like": has_wild}
        else:
            ttype = "flexion_conjugacion_like" if has_wild else "flexion_conjugacion"
            return {"type": ttype, "val": inner_sql, "like": has_wild}

    # ── palabra:cat o palabra*:cat ────────────────────────────────────────────
    if ":" in p_lower:
        idx = p_lower.index(":")
        palabra = p_lower[:idx]
        cat = p_lower[idx + 1:]
        has_wild = "*" in palabra or "?" in palabra
        palabra_sql = palabra.replace("*", "%").replace("?", "_")
        ttype = "palabra_categoria_like" if has_wild else "palabra_categoria"
        return {"type": ttype, "val": palabra_sql, "cat": cat, "like": has_wild}

    # ── palabra* (comodín sin categoría) ─────────────────────────────────────
    if "*" in p_lower or "?" in p_lower:
        val_sql = p_lower.replace("*", "%").replace("?", "_")
        return {"type": "palabra_comodin", "val": val_sql, "like": True}

    # ── palabra exacta → busca por lema en BD (igual que el C# con flexion_conjugacion) ──
    return {"type": "exacto", "val": p_lower, "like": False}


def _token_condition(alias: str, tok: dict) -> tuple[str, list]:
    """
    Genera la condición SQL para un token parseado.
    Devuelve (sql_fragment, params).
    """
    t = tok["type"]
    params = []

    if t == "cat_gramatical":
        cond, _ = _cat_condition(alias, tok["val"])
        return cond, []

    elif t == "flexion_conjugacion":
        return f"{alias}.lema = %s", [tok["val"]]

    elif t == "flexion_conjugacion_like":
        return f"{alias}.lema LIKE %s", [tok["val"]]

    elif t == "flexion_categoria":
        cat_cond, _ = _cat_condition(alias, tok["cat"], general_range="wide")
        return f"({alias}.lema = %s AND {cat_cond})", [tok["val"]]

    elif t == "flexion_categoria_like":
        cat_cond, _ = _cat_condition(alias, tok["cat"], general_range="wide")
        return f"({alias}.lema LIKE %s AND {cat_cond})", [tok["val"]]

    elif t == "palabra_categoria":
        cat_cond, _ = _cat_condition(alias, tok["cat"], general_range="wide")
        return f"(LOWER({alias}.palabra) = %s AND {cat_cond})", [tok["val"]]

    elif t == "palabra_categoria_like":
        cat_cond, _ = _cat_condition(alias, tok["cat"], general_range="wide")
        return f"(LOWER({alias}.palabra) LIKE %s AND {cat_cond})", [tok["val"]]

    elif t == "palabra_comodin":
        return f"LOWER({alias}.palabra) LIKE %s", [tok["val"]]

    else:  # exacto → busca tanto en lema como en palabra (igual que el C#)
        return f"({alias}.lema = %s OR LOWER({alias}.palabra) = %s)", [tok["val"], tok["val"]]


# ── Motor de búsqueda DISECAN (fiel al C# DatabasePattern.cs) ────────────────

def _is_disecan_pattern(text: str) -> bool:
    """Detecta si el texto contiene sintaxis DISECAN avanzada."""
    return bool(re.search(r"[<>\[\]:\*\?]|\d+", text))


def linguistic_search_pattern(pattern_str: str, top_k: int = 100, ordered: bool = True) -> list[dict]:
    """
    Búsqueda DISECAN por patrón lingüístico.

    Implementación fiel a DatabasePattern.cs / DatabasePatternSinOrden.cs:
    - ordered=True  → las palabras deben aparecer en el mismo orden y con
                      la distancia de posición especificada (posElementoFrase - prev = 1 o N+1).
    - ordered=False → las palabras deben estar en la misma frase, sin importar el orden.

    Sintaxis admitida (igual que el buscador original):
      <categoria>           Cualquier palabra de esa categoría gramatical
      [lema]                Cualquier forma del lema (flexión)
      [lema:cat]            Lema restringido a categoría
      [lema*]               Lema con comodín
      [lema*:cat]           Lema con comodín restringido a categoría
      palabra:cat           Palabra exacta restringida a categoría
      palabra*:cat          Palabra con comodín restringida a categoría
      palabra*              Palabra con comodín
      palabra               Lema o forma exacta
      N (número)            Distancia máxima entre el token anterior y el siguiente
    """
    # ── 1. Pre-procesado del input (idéntico al Button_Click de Default.aspx.cs) ──
    text = pattern_str.strip()
    text = re.sub(r"\s+", " ", text)
    # Eliminar dígitos al principio y al final
    text = re.sub(r"^\d+|\d+$", "", text).strip()
    # Normalizar alias de categoría dentro de <...>
    for alias, full in CAT_ALIAS.items():
        text = re.sub(rf"<{re.escape(alias)}>", f"<{full}>", text, flags=re.IGNORECASE)
        text = re.sub(rf":{re.escape(alias)}(\s|$)", f":{full}\\1", text, flags=re.IGNORECASE)
    # Separar ><
    text = re.sub(r"><", "> <", text)
    text = text.strip()

    if not text:
        return []

    # ── 2. Parseo de tokens ────────────────────────────────────────────────────
    # El C# usa regex: <...> | [...]:? | word:?  — aquí replicamos el split manualmente
    raw_parts = text.split()

    # Reconstruir partes que pueden tener espacios dentro de <> (no debería, pero por seguridad)
    parts: list[str] = []
    for rp in raw_parts:
        parts.append(rp)

    tokens: list[dict] = []   # tokens no-número
    distances: list[int] = [] # dist[i] = distancia entre token[i-1] y token[i]
    pending_dist = 1          # distancia por defecto (adyacente)

    for p in parts:
        if re.fullmatch(r"\d+", p):
            pending_dist = int(p) + 1   # igual que en C#: distancia = N+1
            continue
        tok = _parse_token(p)
        tokens.append(tok)
        distances.append(pending_dist)
        pending_dist = 1

    if not tokens:
        return []

    logger.info(f"[DB/Pattern] tokens={[t['type'] for t in tokens]} | ordered={ordered}")

    # ── 3. Construcción del SQL (fiel a DatabasePattern.cs) ───────────────────
    #
    # Estructura general:
    #   SELECT fr.idFrases, fr.orador, fr.idDocumento, <cols_tokens>
    #   FROM (
    #     SELECT DISTINCT fr.idFrases, fr.orador, fr.ByteInicioFrase, fr.ByteLongFrase,
    #            fr.idDocumento
    #     FROM frases AS fr
    #     INNER JOIN palabras AS pal1 ON pal1.idFrase = fr.idFrases <cond1>
    #     [INNER JOIN palabras AS pal2 ON pal2.idFrase = pal1.idFrase <pos> <cond2>]
    #     ...
    #     WHERE <filtros_doc>
    #     LIMIT 0, 100
    #   ) AS fr
    #   INNER JOIN palabras AS pal1 ON pal1.idFrase = fr.idFrases <cond1>
    #   ...

    n = len(tokens)
    params_inner: list = []
    params_outer: list = []

    def build_joins(alias_prefix: str, inner: bool) -> str:
        """Construye los INNER JOINs para la subconsulta (inner=True) o la externa (inner=False)."""
        joins = []
        p_params = params_inner if inner else params_outer

        for i in range(n):
            alias = f"{alias_prefix}{i + 1}"
            tok = tokens[i]
            tok_cond, tok_params = _token_condition(alias, tok)

            if i == 0:
                join = f"INNER JOIN palabras AS {alias} ON {alias}.idFrase = fr.idFrases AND {tok_cond}"
            else:
                prev_alias = f"{alias_prefix}{i}"
                dist = distances[i]

                if ordered:
                    # distancia = 1 → exactamente adyacente (posEleFrase - posEleFrase_prev = 1)
                    # distancia > 1 → entre 1 y dist posiciones (como en el C# con CreatePosItem)
                    if dist == 1:
                        pos_cond = f"{alias}.posElementoFrase - {prev_alias}.posElementoFrase = 1"
                    else:
                        pos_cond = (
                            f"{alias}.posElementoFrase - {prev_alias}.posElementoFrase > 0 "
                            f"AND {alias}.posElementoFrase - {prev_alias}.posElementoFrase <= {dist}"
                        )
                    join = (
                        f"INNER JOIN palabras AS {alias} "
                        f"ON {alias}.idFrase = {prev_alias}.idFrase "
                        f"AND {pos_cond} "
                        f"AND {tok_cond}"
                    )
                else:
                    # Sin orden: solo misma frase
                    join = (
                        f"INNER JOIN palabras AS {alias} "
                        f"ON {alias}.idFrase = {prev_alias}.idFrase "
                        f"AND {tok_cond}"
                    )

            p_params.extend(tok_params)
            joins.append(join)
        return "\n        ".join(joins)

    inner_joins = build_joins("pal", inner=True)
    outer_joins = build_joins("pal", inner=False)

    # Columnas de posición y valor (para poder recuperar las posiciones de cada match)
    cols = []
    for i in range(n):
        alias = f"pal{i + 1}"
        tok = tokens[i]
        if tok["type"] in ("flexion_conjugacion", "flexion_conjugacion_like",
                           "flexion_categoria", "flexion_categoria_like"):
            cols.append(f"{alias}.lema, {alias}.posElementoFrase")
        elif tok["type"] == "cat_gramatical":
            cols.append(f"{alias}.categoria, {alias}.posElementoFrase")
        else:
            cols.append(f"{alias}.palabra, {alias}.posElementoFrase")
    cols_str = ", ".join(cols)

    sql = f"""
        SELECT fr.idFrases AS id_frase,
               fr.orador,
               fr.idDocumento AS id_documento,
               1.0 AS score,
               {cols_str}
        FROM (
            SELECT DISTINCT
                fr.idFrases, fr.orador, fr.ByteInicioFrase, fr.ByteLongFrase,
                fr.idDocumento
            FROM frases AS fr
            {inner_joins}
            LIMIT {top_k}
        ) AS fr
        {outer_joins}
    """

    all_params = params_inner + params_outer

    logger.debug(f"[DB/Pattern] SQL:\n{sql}")
    logger.debug(f"[DB/Pattern] Params: {all_params}")

    try:
        with get_connection() as conn, get_cursor(conn) as cur:
            cur.execute(sql, all_params)
            rows = cur.fetchall()
            logger.info(f"[DB/Pattern] Resultados: {len(rows)}")
            # Simplificar output: solo id_frase, orador, id_documento, score
            seen = set()
            results = []
            for r in rows:
                fid = r["id_frase"]
                if fid not in seen:
                    seen.add(fid)
                    results.append({
                        "id_frase":    r["id_frase"],
                        "orador":      r["orador"],
                        "id_documento": r["id_documento"],
                        "score":       1.0,
                    })
            return results
    except Exception as e:
        logger.error(f"[DB/Pattern] Error ejecutando SQL: {e}")
        logger.debug(f"[DB/Pattern] SQL fallido:\n{sql}")
        logger.debug(f"[DB/Pattern] Params fallidos: {all_params}")
        return []


def linguistic_search(terminos: list[str], top_k: int = 100) -> list[dict]:
    """
    Punto de entrada principal de búsqueda lingüística.

    - Si algún término contiene sintaxis DISECAN (<>, [], :, *, ?) →
      delega en linguistic_search_pattern() con el patrón completo.
    - Si es búsqueda libre → búsqueda por lema (Best Match sobre la tabla palabras).
    """
    if not terminos:
        return []

    # Unir todos los términos en una sola cadena para detectar patrones
    full_query = " ".join(terminos).strip()

    # Detectar si hay sintaxis DISECAN
    if _is_disecan_pattern(full_query):
        logger.info(f"[DB] Modo DISECAN Pattern: '{full_query}'")
        return linguistic_search_pattern(full_query, top_k=top_k, ordered=True)

    # ── Búsqueda libre por lema ───────────────────────────────────────────────
    from backend.lemmatizer import get_lemas

    stopwords = {
        "de", "la", "el", "en", "y", "a", "los", "las", "un", "una",
        "por", "con", "no", "su", "para", "es", "se", "al", "del",
        "que", "lo", "le", "más", "o", "pero", "sus", "ya", "han",
        "ha", "hay", "fue", "era",
    }

    palabras_raw: list[str] = []
    for t in terminos:
        parts = re.findall(r'\w+', t.lower())
        palabras_raw.extend([p for p in parts if p not in stopwords and len(p) > 2])
    palabras_raw = list(set(palabras_raw))

    palabras_busqueda: list[str] = []
    for p in palabras_raw:
        lemas_p = get_lemas(p)
        palabras_busqueda.extend(lemas_p)
    palabras_busqueda = list(set(palabras_busqueda))[:8]

    if not palabras_busqueda:
        return []

    placeholders = ", ".join(["%s"] * len(palabras_busqueda))
    sql = f"""
        SELECT f.idFrases AS id_frase, f.orador, f.idDocumento AS id_documento,
               COUNT(DISTINCT p.lema) AS score
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
            n_lemas = len(palabras_busqueda)
            for r in results:
                r["score"] = r["score"] / n_lemas
            return results
    except Exception as e:
        logger.error(f"[DB] Error en linguistic_search libre: {e}")
        return []
