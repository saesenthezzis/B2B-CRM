import libsql_experimental as libsql

def dict_factory(cursor, row):
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}

con = libsql.connect("file:test.db")
try:
    con.row_factory = dict_factory
    con.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER, name TEXT)")
    con.execute("INSERT INTO test VALUES (1, 'alice')")
    row = con.execute("SELECT * FROM test").fetchone()
    print("Row:", row)
except Exception as e:
    print("Error:", e)
