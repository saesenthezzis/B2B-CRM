import os
import re

APP_PY = "app.py"

with open(APP_PY, "r", encoding="utf-8") as f:
    content = f.read()

DEALS_PATTERN = re.compile(r'@app\.get\("/api/deals"\)\n@login_required\ndef deals\(\):\n(?: {4}.*\n)*', re.MULTILINE)

NEW_DEALS_CODE = """@app.get("/api/deals")
@login_required
def deals():
    try:
        con = core.db()
        
        user_name = session.get("username", "")
        zone_cities = []
        if user_name:
            specialists = core.load_specialists(con)
            for s in specialists:
                if s["name"] == user_name and s["city"]:
                    zone_cities.append(s["city"])
                    
        where_sql, params = core.build_filters_sql(request.args, zone_cities=zone_cities)
        
        sort_col = request.args.get("sortCol", "amount")
        sort_dir = int(request.args.get("sortDir", "-1"))
        
        order_by = sort_col
        if sort_col == "status":
            order_by = f"({core.SQL_LEVEL})"
        elif sort_col not in ("amount", "client", "doc_date", "stage", "city", "doc_num", "in_stock", "plan_contact", "notes", "author"):
            order_by = "amount"
            
        direction = "DESC" if sort_dir == -1 else "ASC"
        order_clause = f"ORDER BY {order_by} {direction}"
        
        page = int(request.args.get("page", "0"))
        limit = 50
        offset = page * limit
        
        query = f"SELECT * FROM deals WHERE {where_sql} {order_clause} LIMIT {limit} OFFSET {offset}"
        rows = [dict(r) for r in con.execute(query, params)]
        
        count_res = list(con.execute(f"SELECT COUNT(*) as c FROM deals WHERE {where_sql}", params))
        total = count_res[0]["c"] if count_res else 0
        
        sum_res = list(con.execute(f"SELECT SUM(amount) as s FROM deals WHERE {where_sql}", params))
        total_sum = sum_res[0]["s"] if sum_res and sum_res[0]["s"] is not None else 0
        
        user_action_keys = {r["deal_key"] for r in con.execute("SELECT DISTINCT deal_key FROM history WHERE user != '1С-импорт'")}
        
        out = []
        for d in rows:
            d.update(core.derive(d, user_action_keys=user_action_keys))
            out.append(d)
            
        return jsonify({
            "items": out,
            "total": total,
            "sum": total_sum
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.get("/api/stats")
@login_required
def stats():
    try:
        con = core.db()
        
        user_name = session.get("username", "")
        zone_cities = []
        if user_name:
            specialists = core.load_specialists(con)
            for s in specialists:
                if s["name"] == user_name and s["city"]:
                    zone_cities.append(s["city"])
                    
        where_sql, params = core.build_filters_sql(request.args, zone_cities=zone_cities)
        
        kpi_sql = f'''
        SELECT 
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) THEN 1 ELSE 0 END) as act_count,
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) THEN amount ELSE 0 END) as act_sum,
            
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) = 'risk' THEN 1 ELSE 0 END) as risk_count,
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) = 'risk' THEN amount ELSE 0 END) as risk_sum,
            
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) = 'ready' THEN 1 ELSE 0 END) as ready_count,
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) = 'ready' THEN amount ELSE 0 END) as ready_sum,
            
            SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_OVERDUE}) = 1 THEN 1 ELSE 0 END) as over_count,
            
            SUM(CASE WHEN ({core.SQL_LEVEL}) = 'error' THEN 1 ELSE 0 END) as err_count,
            
            SUM(CASE WHEN ({core.SQL_LEVEL}) = 'done' THEN 1 ELSE 0 END) as done_count,
            SUM(CASE WHEN ({core.SQL_LEVEL}) = 'done' THEN amount ELSE 0 END) as done_sum,
            
            SUM(CASE WHEN ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) != 'done' THEN 1 ELSE 0 END) as lost_count,
            SUM(CASE WHEN ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) != 'done' THEN amount ELSE 0 END) as lost_sum
        FROM deals WHERE {where_sql}
        '''
        kpi_row = list(con.execute(kpi_sql, params))[0]
        kpi = dict(kpi_row)
        for k, v in kpi.items():
            if v is None: kpi[k] = 0
            
        funnel_sql = f"SELECT COALESCE(stage, '(нет этапа)') as s, SUM(amount) as a FROM deals WHERE {where_sql} GROUP BY s"
        funnel_rows = list(con.execute(funnel_sql, params))
        funnel = {r["s"]: r["a"] or 0 for r in funnel_rows}
        
        lost_sql = f"SELECT COALESCE(NULLIF(reject_reason, ''), NULLIF(delete_reason, ''), '(без причины)') as r, SUM(amount) as a FROM deals WHERE {where_sql} AND ({core.SQL_IS_CLOSED} AND ({core.SQL_LEVEL}) != 'done') GROUP BY r"
        lost_rows = list(con.execute(lost_sql, params))
        lost = {r["r"]: r["a"] or 0 for r in lost_rows}
        
        week_sql = f"SELECT strftime('%Y-W%W', substr(COALESCE(doc_date, created_at), 1, 19)) as w, SUM(amount) as a FROM deals WHERE {where_sql} GROUP BY w"
        week_rows = list(con.execute(week_sql, params))
        weeks = {r["w"]: r["a"] or 0 for r in week_rows if r["w"]}
        
        city_sql = f'''
        SELECT COALESCE(city, '(пусто)') as c, 
               SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) THEN amount ELSE 0 END) as act_sum,
               SUM(CASE WHEN ({core.SQL_LEVEL}) = 'done' THEN amount ELSE 0 END) as done_sum
        FROM deals WHERE {where_sql} GROUP BY c
        '''
        city_rows = list(con.execute(city_sql, params))
        cities = {r["c"]: [r["act_sum"] or 0, r["done_sum"] or 0] for r in city_rows}
        
        mgr_sql = f'''
        SELECT COALESCE(author, '(пусто)') as a,
               COUNT(*) as n,
               SUM(amount) as sum,
               SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) THEN 1 ELSE 0 END) as act,
               SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_LEVEL}) = 'risk' THEN 1 ELSE 0 END) as risk,
               SUM(CASE WHEN ({core.SQL_LEVEL}) = 'error' THEN 1 ELSE 0 END) as err,
               SUM(CASE WHEN NOT ({core.SQL_IS_CLOSED}) AND ({core.SQL_OVERDUE}) = 1 THEN 1 ELSE 0 END) as over,
               SUM(CASE WHEN ({core.SQL_LEVEL}) = 'done' THEN 1 ELSE 0 END) as done
        FROM deals WHERE {where_sql} GROUP BY a
        '''
        mgr_rows = list(con.execute(mgr_sql, params))
        mgrs = {r["a"]: dict(r) for r in mgr_rows}
        
        return jsonify({
            "kpi": kpi,
            "funnel": funnel,
            "lost": lost,
            "weeks": weeks,
            "cities": cities,
            "mgrs": mgrs
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
"""

content = DEALS_PATTERN.sub(NEW_DEALS_CODE, content)

with open(APP_PY, "w", encoding="utf-8") as f:
    f.write(content)
