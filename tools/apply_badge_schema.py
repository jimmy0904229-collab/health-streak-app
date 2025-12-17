"""
Apply missing badge schema changes and seed badge records using provided static badge files.
This script is read-write and will ALTER the production DB. Run only if you intend to modify the DB.

Usage:
    python tools\apply_badge_schema.py

It reads DB connection info from env vars (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT) or falls back
to the values used earlier in the session.
"""
import os
import sys
import psycopg2

DB_HOST = os.environ.get('DB_HOST', 'dpg-d4q6onu3jp1c739cll70-a.oregon-postgres.render.com')
DB_NAME = os.environ.get('DB_NAME', 'health_streak_db')
DB_USER = os.environ.get('DB_USER', 'health_streak_db_user')
DB_PASSWORD = os.environ.get('DB_PASSWORD', "I2z4d9zpoZN6s3JfRO2C4ymmc7wmzv4T")
DB_PORT = os.environ.get('DB_PORT', '5432')
BADGE_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'badges')

BADGE_DEFINITIONS = {
    'streak_3': {'title': '3 Day Streak', 'desc': 'Complete 3 consecutive check-ins', 'slug': 'streak_3', 'image_files': ['3 day.png']},
    'streak_7': {'title': '7 Day Streak', 'desc': 'Complete 7 consecutive check-ins', 'slug': 'streak_7', 'image_files': ['7 day.png']},
    'hours_50': {'title': '50 Hours', 'desc': 'Accumulate 50 hours of activity', 'slug': 'hours_50', 'image_files': ['50 hour.png']},
    'hours_100': {'title': '100 Hours', 'desc': 'Accumulate 100 hours of activity', 'slug': 'hours_100', 'image_files': ['100hour.png']},
    'hours_500': {'title': '500 Hours', 'desc': 'Accumulate 500 hours of activity', 'slug': 'hours_500', 'image_files': ['500 hour.png']},
    'comments_5': {'title': '5 Comments', 'desc': 'Receive 5 comments on your posts', 'slug': 'comments_5', 'image_files': ['5com.png']},
    'likes_10': {'title': '10 Likes', 'desc': 'Receive 10 likes on your posts', 'slug': 'likes_10', 'image_files': ['10good.png']},
    'friends_3': {'title': '3 Friends', 'desc': 'Have 3 friends', 'slug': 'friends_3', 'image_files': ['3friend.png']},
    'friends_10': {'title': '10 Friends', 'desc': 'Have 10 friends', 'slug': 'friends_10', 'image_files': ['10friend.png']},
}

DSN = {
    'host': DB_HOST,
    'dbname': DB_NAME,
    'user': DB_USER,
    'password': DB_PASSWORD,
    'port': DB_PORT,
    'sslmode': 'require'
}

DDL_STATEMENTS = [
    # add columns to badge table
    "ALTER TABLE badge ADD COLUMN IF NOT EXISTS slug VARCHAR(80);",
    "ALTER TABLE badge ADD COLUMN IF NOT EXISTS image_filename VARCHAR(300);",
    "ALTER TABLE badge ADD COLUMN IF NOT EXISTS criteria_json TEXT;",
    "ALTER TABLE badge ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;",
    # ensure unique index on slug
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_badge_slug ON badge (slug);",
    # create user_badge table if not exists
    "CREATE TABLE IF NOT EXISTS user_badge (\n    id SERIAL PRIMARY KEY,\n    user_id INTEGER NOT NULL REFERENCES \"user\"(id) ON DELETE CASCADE,\n    badge_id INTEGER NOT NULL REFERENCES badge(id) ON DELETE CASCADE,\n    earned_at TIMESTAMP WITH TIME ZONE DEFAULT now(),\n    pinned BOOLEAN DEFAULT FALSE\n);"
]


def main():
    print('Connecting to DB:', DSN['host'], 'db:', DSN['dbname'])
    try:
        conn = psycopg2.connect(**DSN)
    except Exception as e:
        print('ERROR: cannot connect to DB:', e)
        sys.exit(2)

    cur = conn.cursor()
    try:
        for s in DDL_STATEMENTS:
            print('Executing:', s)
            cur.execute(s)
        conn.commit()
    except Exception as e:
        print('DDL error:', e)
        conn.rollback()
        cur.close()
        conn.close()
        sys.exit(3)

    # seed badges
    try:
        for slug, info in BADGE_DEFINITIONS.items():
            # check exists
            cur.execute("SELECT id FROM badge WHERE slug = %s", (info['slug'],))
            r = cur.fetchone()
            if r:
                print('Badge exists:', info['slug'])
                continue
            # find image file
            img = None
            for fname in info.get('image_files', []):
                fpath = os.path.join(BADGE_FOLDER, fname)
                if os.path.exists(fpath):
                    img = fname
                    break
            print('Inserting badge:', info['slug'], 'image=', img)
            cur.execute('INSERT INTO badge (title, "desc", slug, image_filename, is_active) VALUES (%s, %s, %s, %s, %s) RETURNING id',
                        (info['title'], info['desc'], info['slug'], img, True))
            bid = cur.fetchone()[0]
            print('Inserted badge id', bid)
        conn.commit()
    except Exception as e:
        print('Seed error:', e)
        conn.rollback()
    finally:
        cur.close()
        conn.close()

    print('Done')

if __name__ == '__main__':
    main()
