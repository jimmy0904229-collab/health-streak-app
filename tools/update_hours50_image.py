"""
Update the badge image_filename for slug 'hours_50' to the correct filename '50hour.png'
Connects to the DB using environment variables or the defaults used previously.
"""
import os
import sys
import psycopg2

DB_HOST = os.environ.get('DB_HOST', 'dpg-d4q6onu3jp1c739cll70-a.oregon-postgres.render.com')
DB_NAME = os.environ.get('DB_NAME', 'health_streak_db')
DB_USER = os.environ.get('DB_USER', 'health_streak_db_user')
DB_PASSWORD = os.environ.get('DB_PASSWORD', "I2z4d9zpoZN6s3JfRO2C4ymmc7wmzv4T")
DB_PORT = os.environ.get('DB_PORT', '5432')

DSN = {
    'host': DB_HOST,
    'dbname': DB_NAME,
    'user': DB_USER,
    'password': DB_PASSWORD,
    'port': DB_PORT,
    'sslmode': 'require'
}

TARGET_SLUG = 'hours_50'
TARGET_FILENAME = '50hour.png'

def main():
    print('Connecting to DB:', DSN['host'])
    try:
        conn = psycopg2.connect(**DSN)
    except Exception as e:
        print('ERROR: cannot connect to DB:', e)
        sys.exit(2)

    cur = conn.cursor()
    try:
        cur.execute("SELECT id, image_filename FROM badge WHERE slug = %s", (TARGET_SLUG,))
        row = cur.fetchone()
        if not row:
            print('Badge with slug', TARGET_SLUG, 'not found')
            return
        print('Before:', row)
        cur.execute('UPDATE badge SET image_filename = %s WHERE slug = %s', (TARGET_FILENAME, TARGET_SLUG))
        conn.commit()
        cur.execute("SELECT id, image_filename FROM badge WHERE slug = %s", (TARGET_SLUG,))
        print('After:', cur.fetchone())
    except Exception as e:
        print('ERROR during update:', e)
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    main()
