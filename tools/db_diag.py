"""
Run read-only diagnostics against the Render Postgres DB
Prints info about the specified username and searches for orphaned references.

Usage: python tools\db_diag.py

The script reads connection info from environment variables if present:
 - DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT
Otherwise it falls back to hard-coded values used earlier in this session.
"""
import os
import sys
import psycopg2
import psycopg2.extras

DB_HOST = os.environ.get('DB_HOST', 'dpg-d4q6onu3jp1c739cll70-a.oregon-postgres.render.com')
DB_NAME = os.environ.get('DB_NAME', 'health_streak_db')
DB_USER = os.environ.get('DB_USER', 'health_streak_db_user')
DB_PASSWORD = os.environ.get('DB_PASSWORD', "I2z4d9zpoZN6s3JfRO2C4ymmc7wmzv4T")
DB_PORT = os.environ.get('DB_PORT', '5432')

TARGET_USERNAME = os.environ.get('TARGET_USERNAME', 'jimmy0904229')

QUERIES = [
    ("user_row", "SELECT id, username, display_name FROM \"user\" WHERE username = %s"),
    ("counts_for_user", "SELECT (SELECT id FROM \"user\" WHERE username=%s) as user_id, (SELECT count(*) FROM post WHERE user_id = (SELECT id FROM \"user\" WHERE username=%s)) as post_count, (SELECT count(*) FROM comment WHERE user_id = (SELECT id FROM \"user\" WHERE username=%s)) as comment_count, (SELECT count(*) FROM \"like\" WHERE user_id = (SELECT id FROM \"user\" WHERE username=%s)) as like_count"),
    ("notification_count", "SELECT count(*) FROM notification WHERE user_id = (SELECT id FROM \"user\" WHERE username=%s) OR actor_id = (SELECT id FROM \"user\" WHERE username=%s) OR post_id IN (SELECT id FROM post WHERE user_id = (SELECT id FROM \"user\" WHERE username=%s))"),
    ("friends_pending", "SELECT (SELECT count(*) FROM friend WHERE owner_id = (SELECT id FROM \"user\" WHERE username=%s) OR friend_name = %s) as friend_count, (SELECT count(*) FROM pending_invite WHERE from_user = %s OR to_user = %s) as pending_count"),
    ("orphan_posts", "SELECT p.id FROM post p LEFT JOIN \"user\" u ON p.user_id = u.id WHERE u.id IS NULL LIMIT 20"),
    ("orphan_notifications_posts", "SELECT n.id FROM notification n LEFT JOIN post p ON n.post_id = p.id WHERE n.post_id IS NOT NULL AND p.id IS NULL LIMIT 20"),
    ("comments_missing_user", "SELECT c.id, c.user_id, c.post_id FROM comment c LEFT JOIN \"user\" u ON c.user_id = u.id WHERE c.user_id IS NOT NULL AND u.id IS NULL LIMIT 20"),
    ("likes_missing_user", "SELECT l.id, l.user_id, l.post_id FROM \"like\" l LEFT JOIN \"user\" u ON l.user_id = u.id WHERE l.user_id IS NOT NULL AND u.id IS NULL LIMIT 20"),
    ("friend_missing_friend_name", "SELECT f.id, f.owner_id, f.friend_name FROM friend f LEFT JOIN \"user\" u ON f.friend_name = u.username WHERE u.username IS NULL LIMIT 20"),
    ("alembic_version", "SELECT version_num FROM alembic_version")
]


def run():
    dsn = {
        'host': DB_HOST,
        'dbname': DB_NAME,
        'user': DB_USER,
        'password': DB_PASSWORD,
        'port': DB_PORT,
        'sslmode': 'require'
    }

    print('Connecting to', DB_HOST, 'db:', DB_NAME, 'user:', DB_USER)
    try:
        conn = psycopg2.connect(**dsn)
    except Exception as e:
        print('ERROR: could not connect to DB:', e)
        sys.exit(2)

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    for name, sql in QUERIES:
        print('\n---', name, '---')
        try:
            # many queries expect the username param 1-4 times; supply appropriately
            if sql.count('%s') >= 4:
                params = (TARGET_USERNAME, TARGET_USERNAME, TARGET_USERNAME, TARGET_USERNAME)
            elif sql.count('%s') == 3:
                params = (TARGET_USERNAME, TARGET_USERNAME, TARGET_USERNAME)
            elif sql.count('%s') == 2:
                params = (TARGET_USERNAME, TARGET_USERNAME)
            elif sql.count('%s') == 1:
                params = (TARGET_USERNAME,)
            else:
                params = None

            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)

            rows = cur.fetchall()
            if not rows:
                print('(no rows)')
            else:
                # print up to first 50 rows
                for r in rows[:50]:
                    print(r)
        except Exception as e:
            print('Query error for', name, e)

    cur.close()
    conn.close()


if __name__ == '__main__':
    run()
