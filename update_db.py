import sqlite3
import os

DB = 'app.db'
DB_PATH = os.path.join(os.path.dirname(__file__), DB)

print('Opening DB:', DB_PATH)
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("PRAGMA table_info('post')")
cols = [r[1] for r in cur.fetchall()]
print('post table columns:', cols)
if 'visibility' not in cols:
    print('Adding visibility column to post...')
    try:
        cur.execute("ALTER TABLE post ADD COLUMN visibility VARCHAR(20) DEFAULT 'public'")
        conn.commit()
        print('Column added.')
    except Exception as e:
        print('Failed to add column:', e)
else:
    print('visibility column already present.')

conn.close()
