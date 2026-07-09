-- migrations/optimize_indexes.sql
-- Description: Drop unused indexes and add covering index for /api/deals filters to eliminate TEMP B-TREE ordering.

-- 1. Drop redundant index `ix_deals_computed_status` 
--    (covered by `ix_deals_status_level` which is on `(computed_status, computed_level)`)
DROP INDEX IF EXISTS ix_deals_computed_status;

-- 2. Drop unused index `ix_deals_status1c`
--    (app now uses `computed_status` instead for all queue filters)
DROP INDEX IF EXISTS ix_deals_status1c;

-- 3. Add composite index for /api/deals filtering and ordering
--    This matches the equality filters (`computed_status`, `city`, `stage`) and ordering (`created_at DESC`)
CREATE INDEX IF NOT EXISTS ix_deals_filters_created 
ON deals(computed_status, city, stage, created_at DESC);
