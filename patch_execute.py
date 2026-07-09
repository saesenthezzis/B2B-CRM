import os
import re

APP_PY = "app.py"
CORE_PY = "core.py"

# --- Patch core.py ---
with open(CORE_PY, "r", encoding="utf-8") as f:
    core_content = f.read()

execute_pattern = re.compile(r"""    def execute\(self, sql, params=None\):
        if self\.is_sqlite:
            if params is not None:
                return self\.con\.execute\(sql, params\)
            return self\.con\.execute\(sql\)
        else:
            args = params if params is not None else \[\]
            result = self\.client\.execute\(sql, args\)
            return _DummyCursor\(result\)""")

new_execute = """    def execute(self, sql, params=None):
        if self.is_sqlite:
            if params is not None:
                return self.con.execute(sql, params)
            return self.con.execute(sql)
        else:
            try:
                if isinstance(params, dict):
                    stmt = libsql_client.Statement(sql, params)
                    result = self.client.execute(stmt)
                else:
                    args = params if params is not None else []
                    result = self.client.execute(sql, args)
                return _DummyCursor(result)
            except Exception as e:
                import traceback
                print(f"[TURSO ERROR] SQL: {sql} | Params: {params}")
                traceback.print_exc()
                raise"""

if "args = params if params is not None else []" in core_content:
    core_content = execute_pattern.sub(new_execute, core_content)
    with open(CORE_PY, "w", encoding="utf-8") as f:
        f.write(core_content)
    print("core.py patched")
else:
    print("Could not find execute method in core.py")

# --- Patch app.py ---
with open(APP_PY, "r", encoding="utf-8") as f:
    app_content = f.read()

# Remove the try...except in deals()
deals_pattern = re.compile(r"""@app\.get\("/api/deals"\)\n@login_required\ndef deals\(\):\n    try:\n([\s\S]*?)    except Exception as e:\n        import traceback\n        traceback\.print_exc\(\)\n        return jsonify\(\{"error": str\(e\)\}\), 500""")
match = deals_pattern.search(app_content)
if match:
    # un-indent the body of the try block by 4 spaces
    body_lines = match.group(1).split('\n')
    new_body = '\n'.join([line[4:] if line.startswith('    ') else line for line in body_lines])
    new_deals = f"""@app.get("/api/deals")
@login_required
def deals():\n{new_body}"""
    app_content = deals_pattern.sub(new_deals, app_content)
    print("app.py patched")
else:
    print("Could not find try/except in deals()")

with open(APP_PY, "w", encoding="utf-8") as f:
    f.write(app_content)
