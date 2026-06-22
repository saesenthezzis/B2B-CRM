import sqlite3
import libsql_client
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

def chunker(seq, size):
    return (seq[pos:pos + size] for pos in range(0, len(seq), size))

def migrate():
    local_con = sqlite3.connect("rmko.db")
    local_con.row_factory = sqlite3.Row
    local_cur = local_con.cursor()

    url = os.getenv("TURSO_DATABASE_URL").replace("libsql://", "https://")
    auth_token = os.getenv("TURSO_AUTH_TOKEN")
    
    if not url or not auth_token:
        print("Missing TURSO_DATABASE_URL or TURSO_AUTH_TOKEN")
        return

    print("Connecting to Turso...")
    client = libsql_client.create_client_sync(url, auth_token=auth_token)

    from core import SCHEMA
    statements = [s.strip() for s in SCHEMA.split(";") if s.strip()]
    client.batch(statements)
    print("Schema created.")

    # 2. Migrate `deals`
    deals = local_cur.execute("SELECT * FROM deals").fetchall()
    print(f"Migrating {len(deals)} deals...")
    if deals:
        columns = deals[0].keys()
        placeholders = ", ".join(["?"] * len(columns))
        insert_sql = f"INSERT OR REPLACE INTO deals ({', '.join(columns)}) VALUES ({placeholders})"
        for i, chunk in enumerate(chunker(deals, 500)):
            stmts = [libsql_client.Statement(insert_sql, list(row)) for row in chunk]
            client.batch(stmts)
            print(f"  ... batch {i+1} inserted")
    print("Deals migrated.")

    # 3. Migrate `history`
    history = local_cur.execute("SELECT * FROM history").fetchall()
    print(f"Migrating {len(history)} history records...")
    if history:
        columns = history[0].keys()
        placeholders = ", ".join(["?"] * len(columns))
        insert_sql = f"INSERT OR REPLACE INTO history ({', '.join(columns)}) VALUES ({placeholders})"
        for i, chunk in enumerate(chunker(history, 500)):
            stmts = [libsql_client.Statement(insert_sql, list(row)) for row in chunk]
            client.batch(stmts)
            print(f"  ... batch {i+1} inserted")
    print("History migrated.")

    # 4. Migrate `meta`
    meta = local_cur.execute("SELECT * FROM meta").fetchall()
    print(f"Migrating {len(meta)} meta records...")
    if meta:
        columns = meta[0].keys()
        placeholders = ", ".join(["?"] * len(columns))
        insert_sql = f"INSERT OR REPLACE INTO meta ({', '.join(columns)}) VALUES ({placeholders})"
        stmts = [libsql_client.Statement(insert_sql, list(row)) for row in meta]
        client.batch(stmts)
    print("Meta migrated.")

    print("Migration complete!")
    local_con.close()
    client.close()

if __name__ == "__main__":
    migrate()
