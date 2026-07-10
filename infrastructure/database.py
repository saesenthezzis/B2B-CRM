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

import json
import urllib.request
import re
from urllib.parse import urlparse, parse_qs

class _DummyCursorRest:
    def __init__(self, data):
        self._data = data
        self._idx = 0
    def fetchone(self):
        if self._idx < len(self._data):
            res = self._data[self._idx]
            self._idx += 1
            return res
        return None
    def fetchall(self):
        res = self._data[self._idx:]
        self._idx = len(self._data)
        return res
    def __iter__(self):
        return iter(self._data)

class DbWrapper:
    def __init__(self, url, auth_token=None):
        self._is_singleton = False  # singleton нельзя закрывать
        self.is_sqlitecloud = url.startswith("sqlitecloud://")
        if self.is_sqlitecloud:
            parsed = urlparse(url)
            self.hostname = parsed.hostname
            self.db_name = parsed.path.lstrip('/')
            qs = parse_qs(parsed.query)
            self.apikey = qs.get('apikey', [''])[0]
            self.api_url = f"https://{self.hostname}/v2/weblite/sql"
            self.headers = {
                'accept': 'application/json',
                'Content-Type': 'application/json',
                'Authorization': f"Bearer sqlitecloud://{self.hostname}:8860?apikey={self.apikey}"
            }
        else:
            path = url.replace("file:", "")
            self.con = sqlite3.connect(path)
            self.con.row_factory = sqlite3.Row
    
    def cursor(self):
        if self.is_sqlitecloud:
            return self
        return self.con.cursor()

    def _convert_params(self, sql, params):
        if not isinstance(params, dict):
            return sql, params
        bind = []
        def replacer(match):
            key = match.group(1)
            if key in params:
                bind.append(params[key])
                return '?'
            return match.group(0)
        new_sql = re.sub(r':([a-zA-Z_][a-zA-Z0-9_]*)', replacer, sql)
        return new_sql, bind

    def _inline_sql(self, sql, params):
        if not params: return sql
        def escape(v):
            if v is None: return "NULL"
            if isinstance(v, (int, float)): return str(v)
            return "'" + str(v).replace("'", "''") + "'"
        if isinstance(params, dict):
            new_sql = sql
            for k, v in sorted(params.items(), key=lambda x: -len(x[0])):
                new_sql = re.sub(r':' + k + r'\b', escape(v), new_sql)
            return new_sql
        else:
            parts = sql.split('?')
            if len(parts) - 1 != len(params): return sql
            res = parts[0]
            for i, v in enumerate(params):
                res += escape(v) + parts[i+1]
            return res

    def _execute_with_retry(self, req):
        import http.client
        import time
        import urllib.error
        retries = 3
        while retries > 0:
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    if 'error' in data: raise Exception(data['error'])
                    return data
            except urllib.error.HTTPError as e:
                if e.code in (500, 502, 503, 504):
                    retries -= 1
                    if retries == 0: raise
                    time.sleep(1)
                else:
                    raise
            except (http.client.IncompleteRead, ConnectionError, TimeoutError, urllib.error.URLError):
                retries -= 1
                if retries == 0: raise
                time.sleep(1)

    def execute(self, sql, params=None, silent=False):
        if self.is_sqlitecloud:
            try:
                is_select = sql.strip().upper().startswith("SELECT")
                if is_select and "LIMIT" not in sql.upper():
                    all_rows = []
                    offset = 0
                    limit = 500
                    while True:
                        paginated_sql = f"{sql} LIMIT {limit} OFFSET {offset}"
                        req_sql = f"USE DATABASE {self.db_name}; {paginated_sql}"
                        payload = {'sql': req_sql}
                        if params is not None:
                            new_sql, bind = self._convert_params(paginated_sql, params)
                            payload['sql'] = f"USE DATABASE {self.db_name}; {new_sql}"
                            if bind: payload['bind'] = bind
                        
                        req = urllib.request.Request(
                            self.api_url, data=json.dumps(payload).encode('utf-8'),
                            headers=self.headers, method='POST'
                        )
                        data = self._execute_with_retry(req)
                        rows = data.get('data', [])
                        all_rows.extend(rows)
                        if len(rows) < limit: break
                        offset += limit
                    return _DummyCursorRest(all_rows)
                else:
                    req_sql = f"USE DATABASE {self.db_name}; {sql}"
                    payload = {'sql': req_sql}
                    if params is not None:
                        new_sql, bind = self._convert_params(sql, params)
                        payload['sql'] = f"USE DATABASE {self.db_name}; {new_sql}"
                        if bind: payload['bind'] = bind
                    
                    req = urllib.request.Request(
                        self.api_url, data=json.dumps(payload).encode('utf-8'),
                        headers=self.headers, method='POST'
                    )
                    data = self._execute_with_retry(req)
                    rows = data.get('data', [])
                    return _DummyCursorRest(rows)
            except Exception as e:
                if not silent:
                    import traceback
                    print(f"[REST DB ERROR] SQL: {sql} | Params: {params}")
                    traceback.print_exc()
                raise
        else:
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
        if self.is_sqlitecloud:
            for stmt in sql_script.split(";"):
                stmt = stmt.strip()
                if stmt:
                    self.execute(stmt)
        else:
            self.con.executescript(sql_script)

    def _is_sqlitecloud(self):
        return self.is_sqlitecloud
    
    def execute_batch(self, statements_list):
        if not statements_list:
            return
        if self.is_sqlitecloud:
            chunk_size = 100
            for i in range(0, len(statements_list), chunk_size):
                chunk = statements_list[i:i+chunk_size]
                combined_sql = "BEGIN; "
                for sql, params in chunk:
                    combined_sql += self._inline_sql(sql, params) + "; "
                combined_sql += "COMMIT;"
                
                payload = {'sql': f"USE DATABASE {self.db_name}; {combined_sql}"}
                req = urllib.request.Request(
                    self.api_url, data=json.dumps(payload).encode('utf-8'),
                    headers=self.headers, method='POST'
                )
                try:
                    self._execute_with_retry(req)
                except Exception as e:
                    import traceback
                    print(f"[REST BATCH ERROR] Chunk {i}. Details: {e}")
                    traceback.print_exc()
                    raise
        else:
            for sql, params in statements_list:
                if params is not None:
                    self.con.execute(sql, params)
                else:
                    self.con.execute(sql)
            self.con.commit()
    
    def commit(self):
        if not self.is_sqlitecloud:
            self.con.commit()
            
    def close(self):
        if self._is_singleton:
            return
        if not self.is_sqlitecloud:
            self.con.close()

import threading

_local_db = threading.local()

def close_db(e=None):
    if hasattr(_local_db, "con"):
        try:
            _local_db.con.con.close()
        except Exception:
            pass
        del _local_db.con

def get_db() -> DbWrapper:
    db_url = os.getenv("DATABASE_URL", "")
    
    if db_url and db_url.startswith("sqlitecloud://"):
        if not hasattr(_local_db, "con"):
            _local_db.con = DbWrapper(db_url)
            _local_db.con._is_singleton = True
        return _local_db.con
    else:
        # Fallback to local
        if not hasattr(_local_db, "con"):
            BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            DB_PATH = os.path.join(BASE, "rmko.db")
            _local_db.con = DbWrapper(f"file:{DB_PATH}")
            _local_db.con._is_singleton = True
        return _local_db.con
