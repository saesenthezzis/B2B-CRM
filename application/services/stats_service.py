# -*- coding: utf-8 -*-
"""Service for calculating statistics."""

import threading
import time
import hashlib
import json

class StatsService:
    _cache = {}
    _cache_lock = threading.Lock()
    _ttl = 300  # 5 minutes

    def __init__(self, deal_repository):
        self.repo = deal_repository

    def get_dashboard_stats(self, where_sql, params):
        key_str = where_sql + json.dumps(params, sort_keys=True)
        cache_key = hashlib.md5(key_str.encode('utf-8')).hexdigest()
        
        now = time.time()
        with self._cache_lock:
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                if now - entry['ts'] < self._ttl:
                    return entry['data']

        performance = self.repo.get_user_performance_stats(where_sql, params)
        daily = self.repo.get_user_daily_activity(where_sql, params)
        
        # Additional KPI data for the Boss Dashboard
        kpi = self.repo.get_kpi_stats(where_sql, params)
        managers = self.repo.get_mgr_stats(where_sql, params)
        funnel = self.repo.get_funnel_stats(where_sql, params)
        cities = self.repo.get_cities_stats(where_sql, params)
        weeks = self.repo.get_weeks_stats(where_sql, params)
        
        result = {
            "performance": performance,
            "daily": daily,
            "kpi": kpi,
            "managers": managers,
            "funnel": funnel,
            "cities": cities,
            "weeks": weeks
        }

        with self._cache_lock:
            self._cache[cache_key] = {'ts': now, 'data': result}
            
        return result

