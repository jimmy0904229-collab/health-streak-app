import os
import psycopg2

def get_conn():
    host = os.environ.get('DB_HOST') or os.environ.get('PGHOST')
    dbname = os.environ.get('DB_NAME') or os.environ.get('PGDATABASE')
    user = os.environ.get('DB_USER') or os.environ.get('PGUSER')
    password = os.environ.get('DB_PASSWORD') or os.environ.get('PGPASSWORD')
    port = os.environ.get('DB_PORT') or os.environ.get('PGPORT') or '5432'
    if not (host and dbname and user):
        print('Missing DB_HOST/DB_NAME/DB_USER (or PGHOST/PGDATABASE/PGUSER)')
        raise SystemExit(1)
    conn = psycopg2.connect(host=host, dbname=dbname, user=user, password=password, port=port, sslmode=os.environ.get('PGSSLMODE','require'))
    return conn

def list_tables_and_columns(conn):
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
    tables = [r[0] for r in cur.fetchall()]
    print('Tables:', tables)
    for t in tables:
        print('\nTable:', t)
        cur.execute("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name=%s ORDER BY ordinal_position", (t,))
        for col in cur.fetchall():
            print('  ', col)

if __name__ == '__main__':
    try:
        conn = get_conn()
    except Exception as e:
        print('Connection failed:', e)
        raise
    try:
        list_tables_and_columns(conn)
    finally:
        conn.close()
