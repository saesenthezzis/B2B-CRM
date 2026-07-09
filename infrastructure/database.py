# -*- coding: utf-8 -*-
"""Database wrapper and connection handling."""

import os
import re
import sqlite3

try:
    import libsql_client
    _HAS_LIBSQL = True
except ImportError:
    libsql_client = None  # type: ignore
    _HAS_LIBSQL = False

class _DummyCursor:
    def __init__(self, rs):
        self.rs = rs
        self._rows = []
        if rs:
            if hasattr(rs, 'rows') and hasattr(rs, 'columns'):
                columns = rs.columns
                for row in rs.rows:
                    d = {columns[i]: row[i] for i in range(len(columns))}
                    self._rows.append(d)
            elif hasattr(rs, 'description') and rs.description:
                columns = [col[0] for col in rs.description]
                for row in rs.fetchall():
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


def _split_sql_script(sql_script):
    return [stmt.strip() for stmt in sql_script.split(";") if stmt.strip()]

def _filter_params(sql, params):
    if not params or not isinstance(params, dict):
        return params
    used = set(re.findall(r":([a-zA-Z_][a-zA-Z0-9_]*)", sql))
    return {k: v for k, v in params.items() if k in used}


class DbWrapper:
    def __init__(self, url, auth_token=None):
        self._is_singleton = False  # singleton нельзя закрывать
        if url.startswith("file:"):
            self.con = sqlite3.connect(url.replace("file:", ""))
            self.con.row_factory = sqlite3.Row
            self.is_sqlite = True
        else:
            if not _HAS_LIBSQL:
                raise RuntimeError("libsql_client is required for remote database URLs")
            remote_url = url.replace("libsql://", "https://")
            self.client = libsql_client.create_client_sync(
                remote_url,
                auth_token=auth_token,
            )
            self.is_sqlite = False
    
    def cursor(self):
        if self.is_sqlite:
            return self.con.cursor()
        return self

    def execute(self, sql, params=None, silent=False):
        if self.is_sqlite:
            if params is not None:
                return self.con.execute(sql, params)
            return self.con.execute(sql)
        else:
            try:
                if isinstance(params, dict):
                    safe_params = _filter_params(sql, params)
                    stmt = libsql_client.Statement(sql, safe_params)
                    result = self.client.execute(stmt)
                else:
                    args = params if params is not None else []
                    result = self.client.execute(sql, args)
                return _DummyCursor(result)
            except Exception as e:
                if not silent:
                    import traceback
                    print(f"[TURSO ERROR] SQL: {sql} | Params: {params}")
                    traceback.print_exc()
                raise

    def executescript(self, sql_script):
        if self.is_sqlite:
            self.con.executescript(sql_script)
        else:
            statements = _split_sql_script(sql_script)
            if statements:
                self.client.batch(statements)
    
    def execute_batch(self, statements_list):
        if not statements_list:
            return
        if self.is_sqlite:
            for sql, params in statements_list:
                if params is not None:
                    self.con.execute(sql, params)
                else:
                    self.con.execute(sql)
            self.con.commit()
        else:
            batch_size = 1000
            for i in range(0, len(statements_list), batch_size):
                chunk = statements_list[i : i + batch_size]
                parts = []
                for sql, params in chunk:
                    if params is None:
                        parts.append(sql)
                    elif isinstance(params, dict):
                        safe_params = _filter_params(sql, params)
                        parts.append(libsql_client.Statement(sql, safe_params))
                    else:
                        parts.append(libsql_client.Statement(sql, params))
                self.client.batch(parts)
    
    def commit(self):
        if self.is_sqlite:
            self.con.commit()
            
    def close(self):
        if self._is_singleton:
            return
        if self.is_sqlite:
            self.con.close()
        else:
            self.client.close()

_db_singleton = None

def get_db() -> DbWrapper:
    global _db_singleton
    if _db_singleton is not None:
        return _db_singleton
        
    db_url = os.getenv("TURSO_DATABASE_URL", "")
    auth_token = os.getenv("TURSO_AUTH_TOKEN", "")
    
    if db_url and db_url.startswith("libsql://"):
        _db_singleton = DbWrapper(db_url, auth_token)
    else:
        # Fallback to local
        BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        DB_PATH = os.path.join(BASE, "rmko.db")
        _db_singleton = DbWrapper(f"file:{DB_PATH}")
        
    _db_singleton._is_singleton = True
    return _db_singleton
