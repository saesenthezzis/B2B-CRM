# -*- coding: utf-8 -*-
"""Database wrapper and connection handling."""

import os
import sqlite3

try:
    import sqlitecloud
    _HAS_SQLITECLOUD = True
except ImportError:
    sqlitecloud = None
    _HAS_SQLITECLOUD = False

class DbWrapper:
    def __init__(self, url, auth_token=None):
        self._is_singleton = False  # singleton нельзя закрывать
        if url.startswith("sqlitecloud://"):
            if not _HAS_SQLITECLOUD:
                raise RuntimeError("sqlitecloud package is required for remote database URLs")
            self.con = sqlitecloud.connect(url)
            self.con.row_factory = sqlitecloud.Row
        else:
            path = url.replace("file:", "")
            self.con = sqlite3.connect(path)
            self.con.row_factory = sqlite3.Row
    
    def cursor(self):
        return self.con.cursor()

    def execute(self, sql, params=None, silent=False):
        try:
            if params is not None:
                return self.con.execute(sql, params)
            return self.con.execute(sql)
        except Exception as e:
            if not silent:
                import traceback
                print(f"[DB ERROR] SQL: {sql} | Params: {params}")
                traceback.print_exc()
            raise

    def executescript(self, sql_script):
        self.con.executescript(sql_script)
    
    def execute_batch(self, statements_list):
        if not statements_list:
            return
        
        for sql, params in statements_list:
            if params is not None:
                self.con.execute(sql, params)
            else:
                self.con.execute(sql)
        self.con.commit()
    
    def commit(self):
        self.con.commit()
            
    def close(self):
        if self._is_singleton:
            return
        self.con.close()

_db_singleton = None

def get_db() -> DbWrapper:
    global _db_singleton
    if _db_singleton is not None:
        return _db_singleton
        
    db_url = os.getenv("DATABASE_URL", "")
    
    if db_url and db_url.startswith("sqlitecloud://"):
        _db_singleton = DbWrapper(db_url)
    else:
        # Fallback to local
        BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        DB_PATH = os.path.join(BASE, "rmko.db")
        _db_singleton = DbWrapper(f"file:{DB_PATH}")
        
    _db_singleton._is_singleton = True
    return _db_singleton
