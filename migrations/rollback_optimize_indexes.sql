-- migrations/rollback_optimize_indexes.sql
-- Description: Rollback the optimization of indexes.

-- 1. Drop the new composite index
DROP INDEX IF EXISTS ix_deals_filters_created;

-- 2. Re-create the unused/redundant indexes
CREATE INDEX IF NOT EXISTS ix_deals_computed_status ON deals(computed_status);
CREATE INDEX IF NOT EXISTS ix_deals_status1c ON deals(status_1c);
