-- =====================================================================
-- Миграция 0010: справочник заказчиков + расширение выручки инструмента
-- (заказчик, номер скважины, часы работы, сутки дежурства, снимок ставок,
-- ссылка на автоматически перенесённую наработку). Выполнить в SQL Editor
-- Supabase (PostgreSQL). Идемпотентна — можно выполнять повторно.
-- =====================================================================

CREATE TABLE IF NOT EXISTS customers (
    id                     SERIAL PRIMARY KEY,
    name                   TEXT NOT NULL,
    contract_number        TEXT NOT NULL DEFAULT '',
    work_rate_rub_per_hour NUMERIC NOT NULL DEFAULT 0,
    standby_rate_rub_per_day NUMERIC NOT NULL DEFAULT 0,
    note                   TEXT NOT NULL DEFAULT '',
    created_by             INTEGER REFERENCES users(id),
    created_at             TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name);

ALTER TABLE tool_revenue ADD COLUMN IF NOT EXISTS customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL;
ALTER TABLE tool_revenue ADD COLUMN IF NOT EXISTS well_number TEXT NOT NULL DEFAULT '';
ALTER TABLE tool_revenue ADD COLUMN IF NOT EXISTS work_hours NUMERIC;
ALTER TABLE tool_revenue ADD COLUMN IF NOT EXISTS standby_days NUMERIC;
ALTER TABLE tool_revenue ADD COLUMN IF NOT EXISTS work_rate_rub_per_hour NUMERIC;
ALTER TABLE tool_revenue ADD COLUMN IF NOT EXISTS standby_rate_rub_per_day NUMERIC;
ALTER TABLE tool_revenue ADD COLUMN IF NOT EXISTS usage_log_id INTEGER REFERENCES tool_usage_logs(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_toolrevenue_customer ON tool_revenue(customer_id);
