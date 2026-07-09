import os
import sys
import json
import time
import requests
from dotenv import load_dotenv
from domain.constants import SQL_IS_CLOSED, SQL_LEVEL, SQL_OVERDUE
from core import build_filters_sql

load_dotenv()

URL = os.getenv('TURSO_DATABASE_URL').replace('libsql://', 'https://') + '/v2/pipeline'
TOKEN = os.getenv('TURSO_AUTH_TOKEN')
HEADERS = {'Authorization': f'Bearer {TOKEN}'}

def exec_sql(query, params=None):
    stmt = {"sql": query}
    if params:
        args = []
        if isinstance(params, dict):
            # filter params to only include those in query
            filtered_params = {k: v for k, v in params.items() if f":{k}" in query}
            for k, v in filtered_params.items():
                args.append({"name": k, "value": {"type": "text", "value": str(v)} if v is not None else {"type": "null"}})
            stmt["named_args"] = args
        elif isinstance(params, (list, tuple)):
            for v in params:
                args.append({"type": "text", "value": str(v)} if v is not None else {"type": "null"})
            stmt["args"] = args
            
    payload = {"requests": [{"type": "execute", "stmt": stmt}]}
    
    resp = requests.post(URL, json=payload, headers=HEADERS, timeout=30)
    if resp.status_code >= 400:
        raise Exception(f"HTTP Error {resp.status_code}: {resp.text}")
    data = resp.json()
    
    res = data["results"][0]
    if res["type"] == "error":
        raise Exception(res["error"]["message"])
    
    rows = []
    cols = [c["name"] for c in res["response"]["result"]["cols"]]
    for r in res["response"]["result"]["rows"]:
        row = {}
        for i, val in enumerate(r):
            row[cols[i]] = val["value"] if "value" in val else None
        rows.append(row)
    return rows

def run_audit():
    results = {}
    with open("audit_results.json", "r", encoding="utf-8") as f:
        results = json.load(f)

    queries_to_explain = []

    args = {"city": "Тюмень", "stage": "В работе", "status": "Резерв"}
    where_sql, params = build_filters_sql(args)
    q1 = f"SELECT * FROM deals WHERE {where_sql} ORDER BY created_at DESC LIMIT 50 OFFSET 0"
    queries_to_explain.append({"name": "/api/deals (filtered)", "query": q1, "params": params})

    q2 = f'''
    SELECT 
        SUM(CASE WHEN NOT ({SQL_IS_CLOSED}) THEN 1 ELSE 0 END) as act_count
    FROM deals WHERE {where_sql}
    '''
    queries_to_explain.append({"name": "/api/stats (filtered)", "query": q2, "params": params})

    explain_results = results.get('explains', {})
    
    print("Running EXPLAINS...", flush=True)
    for q in queries_to_explain:
        print(f"  -> {q['name']}", flush=True)
        try:
            exp = exec_sql(f"EXPLAIN QUERY PLAN {q['query']}", q['params'])
            
            t0 = time.time()
            if "LIMIT" not in q['query'] and "SUM(" not in q['query'] and "COUNT(" not in q['query'] and "history" not in q['query']:
                count_q = f"SELECT count(*) as c FROM ({q['query']})"
                row_cnt = int(exec_sql(count_q, q['params'])[0]['c'])
            else:
                res = exec_sql(q['query'], q['params'])
                row_cnt = len(res)
            t1 = time.time()
            
            explain_results[q['name']] = {
                "explain": exp,
                "rows_returned": row_cnt,
                "actual_time_ms": round((t1 - t0) * 1000, 2)
            }
        except Exception as e:
            explain_results[q['name']] = {"error": str(e)}

    results['explains'] = explain_results

    with open("audit_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    run_audit()
    print("Audit complete.", flush=True)
