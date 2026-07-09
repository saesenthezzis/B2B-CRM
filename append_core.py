import os

CODE = """

# --- SQL Builders for Backend Pagination ---
SQL_STATUS = '''
COALESCE(
  CASE WHEN status_1c IN ('Выдан', 'Резерв', 'Удален', 'Удалён', 'Прочее') THEN status_1c ELSE NULL END,
  CASE WHEN deleted = 1 THEN 'Удален'
       WHEN posted = 1 AND reserved = 0 THEN 'Выдан'
       ELSE 'Резерв' END
)
'''

SQL_HAS_ERROR = f'''
CASE
  WHEN stage = 'Закрыто' AND (in_stock NOT IN ('Проверено', 'Товар есть') OR close_date IS NULL OR close_date = '') THEN 1
  WHEN stage = 'Удалён' AND {SQL_STATUS} NOT IN ('Удален', 'Удалён') THEN 1
  WHEN stage = 'Не состоялась' AND (reject_reason IS NULL OR reject_reason = '' OR close_date IS NULL OR close_date = '') THEN 1
  ELSE 0
END
'''

SQL_IS_PAID = "(has_payment = 1 OR COALESCE(payment_amount, 0) > 0 OR payment_date IS NOT NULL)"

SQL_LEVEL = f'''
CASE
  WHEN {SQL_STATUS} IN ('Удален', 'Удалён') THEN
    CASE WHEN notes IS NULL OR notes = '' THEN 'error' ELSE 'closed' END
  WHEN ({SQL_HAS_ERROR}) = 1 THEN 'error'
  WHEN {SQL_STATUS} = 'Выдан' THEN 'done'
  WHEN {SQL_STATUS} = 'Резерв' AND {SQL_IS_PAID} THEN 'ready'
  WHEN {SQL_STATUS} = 'Резерв' AND substr(COALESCE(doc_date, created_at), 1, 10) <= :risk_date THEN 'risk'
  WHEN {SQL_STATUS} = 'Резерв' THEN 'warn'
  ELSE 'info'
END
'''

SQL_OVERDUE = f'''
CASE WHEN substr(COALESCE(doc_date, created_at), 1, 10) <= :overdue_date 
  AND ({SQL_LEVEL}) NOT IN ('done', 'closed') 
  AND NOT {SQL_IS_PAID} THEN 1 ELSE 0 END
'''

SQL_IS_CLOSED = f"(({SQL_LEVEL}) IN ('done', 'closed') AND ({SQL_HAS_ERROR}) = 0)"

def get_workdays_ago(days):
    from datetime import date, timedelta
    cur = date.today()
    added = 0
    while added < days:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur.strftime("%Y-%m-%d")

def build_filters_sql(args, zone_cities=None):
    where = ["1=1"]
    params = {}
    params["risk_date"] = get_workdays_ago(3)
    params["overdue_date"] = get_workdays_ago(2)

    city = args.get("city", "")
    if city == "__zone__":
        if zone_cities:
            placeholders = ", ".join(f":city_{i}" for i in range(len(zone_cities)))
            where.append(f"city IN ({placeholders})")
            for i, c in enumerate(zone_cities):
                params[f"city_{i}"] = c
        else:
            where.append("1=0") # No cities
    elif city:
        where.append("city = :city")
        params["city"] = city

    stage = args.get("stage", "")
    if stage == "(пусто)":
        where.append("(stage IS NULL OR stage = '')")
    elif stage:
        where.append("stage = :stage")
        params["stage"] = stage

    status = args.get("status", "")
    if status:
        where.append(f"{SQL_STATUS} = :status")
        params["status"] = status

    payment = args.get("payment", "")
    if payment == "paid":
        where.append(SQL_IS_PAID)
    elif payment == "unpaid":
        where.append(f"NOT {SQL_IS_PAID}")

    mine = args.get("mine", "false") == "true"
    me = args.get("me", "")
    if mine and me:
        where.append("LOWER(author) LIKE :me")
        params["me"] = f"%{me.lower()}%"

    range_from = args.get("fFrom", "")
    range_to = args.get("fTo", "")
    
    # Check if period is predefined
    period = args.get("period", "")
    if period and period != "manual":
        from datetime import date, timedelta
        t = date.today()
        range_to = t.strftime("%Y-%m-%d")
        if period == "today":
            range_from = range_to
        elif period == "day":
            range_from = (t - timedelta(days=1)).strftime("%Y-%m-%d")
        elif period == "week":
            range_from = (t - timedelta(days=7)).strftime("%Y-%m-%d")
        elif period == "month":
            range_from = (t - timedelta(days=30)).strftime("%Y-%m-%d")
        elif period == "year":
            range_from = (t - timedelta(days=365)).strftime("%Y-%m-%d")

    if range_from:
        where.append("substr(COALESCE(doc_date, created_at), 1, 10) >= :range_from")
        params["range_from"] = range_from
    if range_to:
        where.append("substr(COALESCE(doc_date, created_at), 1, 10) <= :range_to")
        params["range_to"] = range_to

    q = args.get("q", "").lower()
    if q:
        where.append("(LOWER(COALESCE(client,'')) LIKE :q OR LOWER(COALESCE(doc_num,'')) LIKE :q OR LOWER(COALESCE(comment_1c,'')) LIKE :q OR LOWER(COALESCE(notes,'')) LIKE :q OR LOWER(COALESCE(contacts,'')) LIKE :q)")
        params["q"] = f"%{q}%"

    queue = args.get("queue", "new")
    if queue == "new":
        where.append(f"{SQL_STATUS} = 'Резерв'")
    elif queue == "action":
        where.append(f'''(
            ({SQL_STATUS} = 'Резерв' AND NOT {SQL_IS_PAID}) OR 
            ({SQL_STATUS} IN ('Удален', 'Удалён') AND (notes IS NULL OR notes = '')) OR 
            ({SQL_STATUS} = 'Резерв' AND {SQL_IS_PAID} AND {SQL_STATUS} != 'Выдан')
        )''')
    elif queue == "done":
        where.append(f"{SQL_STATUS} = 'Выдан'")
    elif queue == "lost":
        where.append(f'''(
            ({SQL_STATUS} IN ('Удален', 'Удалён') AND notes IS NOT NULL AND notes != '') OR 
            ({SQL_IS_CLOSED} AND ({SQL_LEVEL}) != 'done')
        )''')

    return " AND ".join(where), params
"""

with open("core.py", "a", encoding="utf-8") as f:
    f.write(CODE)
