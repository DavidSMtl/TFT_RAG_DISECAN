import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
os.environ['PYTHONIOENCODING'] = 'utf-8'

from backend.db import get_connection, get_cursor

with get_connection() as conn, get_cursor(conn) as cur:
    # Ver categorias de 'hablar'
    cur.execute("SELECT DISTINCT categoria FROM palabras WHERE lema = 'hablar' LIMIT 20")
    rows = cur.fetchall()
    print('Categorias de hablar:', [r['categoria'] for r in rows])
    
    # Rango de verbos
    cur.execute("SELECT MIN(categoria), MAX(categoria), COUNT(*) as cnt FROM palabras WHERE categoria >= 3000 AND categoria < 4000")
    row = cur.fetchone()
    print(f"Verbos - min: {row['MIN(categoria)']}, max: {row['MAX(categoria)']}, count: {row['cnt']}")
    
    # Primeras categorías verbales
    cur.execute("SELECT DISTINCT categoria FROM palabras WHERE categoria >= 3000 AND categoria < 3010 LIMIT 20")
    rows = cur.fetchall()
    print('Primeras cats verbo:', [r['categoria'] for r in rows])
    
    # Categorías sustantivo
    cur.execute("SELECT DISTINCT categoria FROM palabras WHERE categoria >= 1000 AND categoria < 1100 LIMIT 20")
    rows = cur.fetchall()
    print('Cats sustantivo:', [r['categoria'] for r in rows])
    
    # Con [hablar:verbo] - probar manualmente
    cur.execute("SELECT COUNT(*) as cnt FROM palabras WHERE lema = 'hablar' AND categoria > 3000 AND categoria < 3007")
    row = cur.fetchone()
    print(f"hablar con verbo(general >3000 <3007): {row['cnt']}")
    
    cur.execute("SELECT COUNT(*) as cnt FROM palabras WHERE lema = 'hablar' AND categoria >= 3000 AND categoria < 4000")
    row = cur.fetchone()
    print(f"hablar con verbo(3000-3999): {row['cnt']}")
