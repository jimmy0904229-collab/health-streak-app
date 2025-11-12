import sqlite3, os
DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'app.db')
print('Updating DB:', DB_PATH)
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("PRAGMA table_info('post')")
cols = [r[1] for r in cur.fetchall()]
print('post columns before:', cols)
if 'visibility' not in cols:
    try:
        cur.execute("ALTER TABLE post ADD COLUMN visibility VARCHAR(20) DEFAULT 'public'")
        conn.commit()
        print('Added visibility column')
    except Exception as e:
        print('Failed to add column:', e)
else:
    print('visibility exists')
conn.close()
