# -*- coding: utf-8 -*-
"""Service for calculating statistics."""

class StatsService:
    def __init__(self, deal_repository):
        self.repo = deal_repository

    def get_dashboard_stats(self, where_sql, params):
        kpi = self.repo.get_kpi_stats(where_sql, params)
        for k, v in kpi.items():
            if v is None: kpi[k] = 0
            
        funnel = self.repo.get_funnel_stats(where_sql, params)
        lost = self.repo.get_lost_stats(where_sql, params)
        weeks = self.repo.get_weeks_stats(where_sql, params)
        cities = self.repo.get_cities_stats(where_sql, params)
        mgrs = self.repo.get_mgr_stats(where_sql, params)
        
        return {
            "kpi": kpi,
            "funnel": funnel,
            "lost": lost,
            "weeks": weeks,
            "cities": cities,
            "mgrs": mgrs
        }
