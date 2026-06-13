import libsql_client
import sqlite3
import os

class DummyCursor:
    def __init__(self, rs):
        self.rs = rs
        self._rows = []
        if rs and hasattr(rs, 'rows'):
            columns = rs.columns
            for row in rs.rows:
                d = {columns[i]: row[i] for i in range(len(columns))}
                self._rows.append(d)
        self._idx = 0

    def fetchone(self):
        if self._idx < len(self._rows):
            res = self._rows[self._idx]
            self._idx += 1
            return res
        return None

    def fetchall(self):
        res = self._rows[self._idx:]
        self._idx = len(self._rows)
        return res

    def __iter__(self):
        return iter(self._rows)

class DbWrapper:
    def __init__(self, url="file:test.db", auth_token=""):
        if url.startswith("file:"):
            self.con = sqlite3.connect(url.replace("file:", ""))
            self.con.row_factory = sqlite3.Row
            self.is_sqlite = True
        else:
            self.client = libsql_client.create_client_sync(url, auth_token=auth_token)
            self.is_sqlite = False
    
    def cursor(self):
        if self.is_sqlite:
            return self.con.cursor()
        return self

    def execute(self, sql, params=None):
        if self.is_sqlite:
            if params is not None:
                return self.con.execute(sql, params)
            return self.con.execute(sql)
        else:
            args = params if params is not None else []
            rs = self.client.execute(sql, args)
            return DummyCursor(rs)

    def executescript(self, sql_script):
        if self.is_sqlite:
            self.con.executescript(sql_script)
        else:
            statements = [s.strip() for s in sql_script.split(";") if s.strip()]
            if statements:
                self.client.execute_batch(statements)
    
    def commit(self):
        if self.is_sqlite:
            self.con.commit()
            
    def close(self):
        if self.is_sqlite:
            self.con.close()
        else:
            self.client.close()

if __name__ == "__main__":
    db = DbWrapper("file:test2.db")
    db.executescript("CREATE TABLE IF NOT EXISTS test (id INTEGER, name TEXT);")
    db.execute("INSERT INTO test VALUES (?, ?)", (1, "alice"))
    db.commit()
    row = db.execute("SELECT * FROM test WHERE name=:name", {"name": "alice"}).fetchone()
    print("Row dict:", dict(row))
    db.close()
