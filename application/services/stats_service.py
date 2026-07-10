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
        
        result = {
            "performance": performance,
            "daily": daily
        }

        with self._cache_lock:
            self._cache[cache_key] = {'ts': now, 'data': result}
            
        return result

