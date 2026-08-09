-- Migration: Add MySQL dialect support (Dual SQL Approach)
-- Run this against the database container.

ALTER TABLE core.problem_datasets
    ADD COLUMN IF NOT EXISTS mysql_schema_sql TEXT,
    ADD COLUMN IF NOT EXISTS mysql_seed_sql TEXT;

ALTER TABLE core.problem_solutions
    ADD COLUMN IF NOT EXISTS mysql_reference_query TEXT;
