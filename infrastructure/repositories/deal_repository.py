# -*- coding: utf-8 -*-
"""Deal repository for database interactions."""

from domain.constants import SQL_IS_CLOSED, SQL_LEVEL, SQL_OVERDUE

class DealRepository:
    def __init__(self, db_wrapper):
        self.db = db_wrapper

    def get_deals(self, where_sql, params, order_clause, limit, offset):
        query = f"SELECT * FROM deals WHERE {where_sql} {order_clause} LIMIT {limit} OFFSET {offset}"
        rows = [dict(r) for r in self.db.execute(query, params)]
        return rows

    def get_deals_aggregates(self, where_sql, params):
        query = f"SELECT COUNT(*) as c, COALESCE(SUM(amount), 0) as s FROM deals WHERE {where_sql}"
        agg_res = list(self.db.execute(query, params))
        total = agg_res[0]["c"] if agg_res else 0
        total_sum = agg_res[0]["s"] if agg_res else 0
        return total, total_sum

    def get_user_actions_for_keys(self, page_keys):
        if not page_keys:
            return set()
        placeholders = ", ".join(f":dk_{i}" for i in range(len(page_keys)))
        dk_params = {f"dk_{i}": k for i, k in enumerate(page_keys)}
        query = f"SELECT DISTINCT deal_key FROM history WHERE deal_key IN ({placeholders}) AND user != '1С-импорт'"
        action_rows = self.db.execute(query, dk_params)
        return {r["deal_key"] for r in action_rows}

    def get_kpi_stats(self, where_sql, params):
        kpi_sql = f'''
        SELECT 
            SUM(CASE WHEN NOT ({SQL_IS_CLOSED}) THEN 1 ELSE 0 END) as act_count,
            SUM(CASE WHEN NOT ({SQL_IS_CLOSED}) THEN amount ELSE 0 END) as act_sum,
            
            SUM(CASE WHEN NOT ({SQL_IS_CLOSED}) AND ({SQL_LEVEL}) = 'risk' THEN 1 ELSE 0 END) as risk_count,
            SUM(CASE WHEN NOT ({SQL_IS_CLOSED}) AND ({SQL_LEVEL}) = 'risk' THEN amount ELSE 0 END) as risk_sum,
            
            SUM(CASE WHEN NOT ({SQL_IS_CLOSED}) AND ({SQL_LEVEL}) = 'ready' THEN 1 ELSE 0 END) as ready_count,
            SUM(CASE WHEN NOT ({SQL_IS_CLOSED}) AND ({SQL_LEVEL}) = 'ready' THEN amount ELSE 0 END) as ready_sum,
            
            SUM(CASE WHEN NOT ({SQL_IS_CLOSED}) AND ({SQL_OVERDUE}) = 1 THEN 1 ELSE 0 END) as over_count,
            
            SUM(CASE WHEN ({SQL_LEVEL}) = 'error' THEN 1 ELSE 0 END) as err_count,
            
            SUM(CASE WHEN ({SQL_LEVEL}) = 'done' THEN 1 ELSE 0 END) as done_count,
            SUM(CASE WHEN ({SQL_LEVEL}) = 'done' THEN amount ELSE 0 END) as done_sum,
            
            SUM(CASE WHEN ({SQL_IS_CLOSED}) AND ({SQL_LEVEL}) != 'done' THEN 1 ELSE 0 END) as lost_count,
            SUM(CASE WHEN ({SQL_IS_CLOSED}) AND ({SQL_LEVEL}) != 'done' THEN amount ELSE 0 END) as lost_sum
        FROM deals WHERE {where_sql}
        '''
        kpi_row = list(self.db.execute(kpi_sql, params))[0]
        return dict(kpi_row)

    def get_funnel_stats(self, where_sql, params):
        funnel_sql = f'''
        SELECT 
            CASE 
                WHEN computed_status = 'Выдан' THEN 'Выданы'
                WHEN computed_status = 'Резерв' AND has_payment = 1 THEN 'В резерве (оплачено)'
                WHEN computed_status = 'Резерв' AND (has_payment = 0 OR has_payment IS NULL) THEN 'В резерве (не оплачено)'
                WHEN computed_status IN ('Удален', 'Удалён') THEN 'Удалены без продажи'
                ELSE 'Прочее'
            END as s,
            SUM(amount) as a
        FROM deals WHERE {where_sql} GROUP BY s
        '''
        funnel_rows = list(self.db.execute(funnel_sql, params))
        return {r["s"]: r["a"] or 0 for r in funnel_rows}

    def get_lost_stats(self, where_sql, params):
        lost_sql = f"SELECT COALESCE(NULLIF(reject_reason, ''), NULLIF(delete_reason, ''), '(без причины)') as r, SUM(amount) as a FROM deals WHERE {where_sql} AND ({SQL_IS_CLOSED} AND ({SQL_LEVEL}) != 'done') GROUP BY r"
        lost_rows = list(self.db.execute(lost_sql, params))
        return {r["r"]: r["a"] or 0 for r in lost_rows}

    def get_weeks_stats(self, where_sql, params):
        week_sql = f"SELECT strftime('%Y-W%W', substr(COALESCE(doc_date, created_at), 1, 19)) as w, SUM(amount) as a FROM deals WHERE {where_sql} GROUP BY w"
        week_rows = list(self.db.execute(week_sql, params))
        return {r["w"]: r["a"] or 0 for r in week_rows if r["w"]}

    def get_cities_stats(self, where_sql, params):
        city_sql = f'''
        SELECT COALESCE(city, '(пусто)') as c, 
               SUM(CASE WHEN NOT ({SQL_IS_CLOSED}) THEN amount ELSE 0 END) as act_sum,
               SUM(CASE WHEN ({SQL_LEVEL}) = 'done' THEN amount ELSE 0 END) as done_sum
        FROM deals WHERE {where_sql} GROUP BY c
        '''
        city_rows = list(self.db.execute(city_sql, params))
        return {r["c"]: [r["act_sum"] or 0, r["done_sum"] or 0] for r in city_rows}

    def get_mgr_stats(self, where_sql, params):
        mgr_sql = f'''
        SELECT COALESCE(author, '(пусто)') as a,
               COUNT(*) as n,
               SUM(amount) as sum,
               SUM(CASE WHEN NOT ({SQL_IS_CLOSED}) THEN 1 ELSE 0 END) as act,
               SUM(CASE WHEN NOT ({SQL_IS_CLOSED}) AND ({SQL_LEVEL}) = 'risk' THEN 1 ELSE 0 END) as risk,
               SUM(CASE WHEN ({SQL_LEVEL}) = 'error' THEN 1 ELSE 0 END) as err,
               SUM(CASE WHEN NOT ({SQL_IS_CLOSED}) AND ({SQL_OVERDUE}) = 1 THEN 1 ELSE 0 END) as over,
               SUM(CASE WHEN ({SQL_LEVEL}) = 'done' THEN 1 ELSE 0 END) as done
        FROM deals WHERE {where_sql} GROUP BY a
        '''
        mgr_rows = list(self.db.execute(mgr_sql, params))
        return {r["a"]: dict(r) for r in mgr_rows}

    def get_dashboard_raw_deals(self, where_sql, params):
        query = f"SELECT COALESCE(doc_date, created_at) as date, amount, city, author, stage, client FROM deals WHERE {where_sql} ORDER BY date ASC"
        return list(self.db.execute(query, params))

    def get_dashboard_structure(self, where_sql, params, group_col):
        query = f"SELECT COALESCE({group_col}, '(не указано)') as label, SUM(amount) as val FROM deals WHERE {where_sql} GROUP BY label ORDER BY val DESC LIMIT 12"
        return list(self.db.execute(query, params))

    def get_dashboard_rating(self, where_sql, params):
        query = f"SELECT COALESCE(client, '(не указано)') as label, SUM(amount) as val FROM deals WHERE {where_sql} GROUP BY label ORDER BY val DESC LIMIT 10"
        return list(self.db.execute(query, params))

    def get_user_performance_stats(self, where_sql, params):
        query = f'''
        SELECT 
            h.user as user,
            COUNT(*) as total_actions,
            COUNT(DISTINCT h.deal_key) as deals_touched,
            SUM(CASE WHEN h.field='notes' THEN 1 ELSE 0 END) as notes_added,
            SUM(CASE WHEN h.field='stage' THEN 1 ELSE 0 END) as stages_changed,
            SUM(CASE WHEN h.field='has_payment' AND h.new_val IN ('1', 'True', 'true', 'Да') THEN 1 ELSE 0 END) as payments_marked,
            SUM(CASE WHEN h.field='in_stock' AND h.new_val='Проверено' THEN 1 ELSE 0 END) as stock_checked
        FROM history h
        JOIN deals d ON h.deal_key = d.key
        WHERE {where_sql} AND h.user != '1С-импорт'
        GROUP BY h.user
        '''
        rows = list(self.db.execute(query, params))
        return {r["user"]: dict(r) for r in rows}

    def get_user_daily_activity(self, where_sql, params):
        query = f'''
        SELECT 
            h.user as user,
            substr(h.ts, 1, 10) as date,
            COUNT(*) as actions
        FROM history h
        JOIN deals d ON h.deal_key = d.key
        WHERE {where_sql} AND h.user != '1С-импорт'
        GROUP BY h.user, substr(h.ts, 1, 10)
        ORDER BY substr(h.ts, 1, 10) ASC
        '''
        rows = list(self.db.execute(query, params))
        return [dict(r) for r in rows]
