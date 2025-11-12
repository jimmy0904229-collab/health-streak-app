import sqlite3, os

for fname in ['app.db', os.path.join('instance','app.db')]:
    path = os.path.abspath(fname)
    print('\nDB:', path)
    if not os.path.exists(path):
        print('  (missing)')
        continue
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        print('  tables:', tables)
        for t in tables:
            print('  schema for', t)
            cur.execute(f"PRAGMA table_info('{t}')")
            for col in cur.fetchall():
                print('   ', col)
    except Exception as e:
        print('  error reading:', e)
    conn.close()
