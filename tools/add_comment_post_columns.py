import sqlite3, os
DB = os.path.join(os.path.dirname(__file__), '..', 'instance', 'app.db')
DB = os.path.abspath(DB)
print('Opening', DB)
conn = sqlite3.connect(DB)
cur = conn.cursor()

def has_col(table, col):
    cur.execute(f"PRAGMA table_info('{table}')")
    cols = [r[1] for r in cur.fetchall()]
    return col in cols

if not has_col('post', 'shared_from_id'):
    try:
        cur.execute("ALTER TABLE post ADD COLUMN shared_from_id INTEGER")
        print('Added post.shared_from_id')
    except Exception as e:
        print('post alter failed', e)

if not has_col('comment', 'user_id'):
    try:
        cur.execute("ALTER TABLE comment ADD COLUMN user_id INTEGER")
        print('Added comment.user_id')
    except Exception as e:
        print('comment.user_id alter failed', e)

if not has_col('comment', 'avatar'):
    try:
        cur.execute("ALTER TABLE comment ADD COLUMN avatar VARCHAR(300)")
        print('Added comment.avatar')
    except Exception as e:
        print('comment.avatar alter failed', e)

conn.commit()
conn.close()

print('Done')
