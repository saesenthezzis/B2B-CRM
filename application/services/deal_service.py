# -*- coding: utf-8 -*-
"""Service for deal listing and transformations."""

import core  # For build_filters_sql and derive

class DealService:
    def __init__(self, deal_repository):
        self.repo = deal_repository

    def get_deals(self, user_name, request_args):
        # We temporarily depend on core to get the db connection for load_specialists,
        # but in a complete refactor, specialist loading should be in a SpecialistService.
        con = self.repo.db
        
        target_user = request_args.get("me") or user_name
        zone_cities = []
        if target_user:
            specialists = core.load_specialists(con)
            for s in specialists:
                if s["name"] == target_user and s["city"]:
                    zone_cities.append(s["city"])
                    
        where_sql, params = core.build_filters_sql(request_args, zone_cities=zone_cities)
        
        sort_col = request_args.get("sortCol", "amount")
        sort_dir = int(request_args.get("sortDir", "-1"))
        
        order_by = sort_col
        if sort_col == "status":
            order_by = "computed_level"
        elif sort_col not in ("amount", "client", "doc_date", "stage", "city", "doc_num", "in_stock", "plan_contact", "notes", "author"):
            order_by = "amount"
            
        direction = "DESC" if sort_dir == -1 else "ASC"
        order_clause = f"ORDER BY {order_by} {direction}"
        
        page = int(request_args.get("page", "0"))
        limit = 50
        offset = page * limit
        
        # 1. Fetch raw deals
        raw_deals = self.repo.get_deals(where_sql, params, order_clause, limit, offset)
        
        # 2. Fetch user actions
        page_keys = [r["key"] for r in raw_deals]
        user_action_keys = self.repo.get_user_actions_for_keys(page_keys)
        
        # 3. Derive computed fields
        out = []
        for d in raw_deals:
            d.update(core.derive(d, user_action_keys=user_action_keys))
            out.append(d)
            
        return {
            "items": out
        }

    def get_deals_summary(self, user_name, request_args):
        con = self.repo.db
        
        target_user = request_args.get("me") or user_name
        zone_cities = []
        if target_user:
            specialists = core.load_specialists(con)
            for s in specialists:
                if s["name"] == target_user and s["city"]:
                    zone_cities.append(s["city"])
                    
        where_sql, params = core.build_filters_sql(request_args, zone_cities=zone_cities)
        
        total, total_sum = self.repo.get_deals_aggregates(where_sql, params)
        kpi = self.repo.get_kpi_stats(where_sql, params)
        for k, v in kpi.items():
            if v is None: kpi[k] = 0
            
        return {
            "total": total,
            "sum": total_sum,
            "kpi": kpi
        }
