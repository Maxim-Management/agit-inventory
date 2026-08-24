-- =====================================================================
-- Миграция 0011: ставки заказчика по типоразмеру инструмента (4 3/4",
-- 6 3/4", 8"), выбор единицы измерения ставки "Работа" (час/сутки) и
-- отдельное поле фактических часов, переносимых в наработку инструмента,
-- когда ставка задана в сутках. ВЫПОЛНЯТЬ ПОСЛЕ 0010 (использует колонки,
-- которые она создаёт). Выполнить в SQL Editor Supabase (PostgreSQL).
-- =====================================================================

-- Ставки заказчика теперь по каждому типоразмеру отдельно, вместо одной
-- ставки на заказчика.
CREATE TABLE IF NOT EXISTS customer_rates (
    id                        SERIAL PRIMARY KEY,
    customer_id               INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    tool_size                 TEXT NOT NULL,
    work_rate                 NUMERIC NOT NULL DEFAULT 0,
    work_rate_unit            TEXT NOT NULL DEFAULT 'hour' CHECK (work_rate_unit IN ('hour', 'day')),
    standby_rate_rub_per_day  NUMERIC NOT NULL DEFAULT 0,
    UNIQUE (customer_id, tool_size)
);
CREATE INDEX IF NOT EXISTS idx_customerrates_customer ON customer_rates(customer_id);

-- Перенос прежней единой ставки каждого заказчика в ставки по всем трём
-- типоразмерам (дальше их можно развести по-разному в карточке заказчика).
-- Если у вас ещё не было ни одного заказчика — просто ничего не вставится.
INSERT INTO customer_rates (customer_id, tool_size, work_rate, work_rate_unit, standby_rate_rub_per_day)
SELECT c.id, ts.tool_size, COALESCE(c.work_rate_rub_per_hour, 0), 'hour', COALESCE(c.standby_rate_rub_per_day, 0)
FROM customers c CROSS JOIN (VALUES ('4 3/4'), ('6 3/4'), ('8')) AS ts(tool_size)
ON CONFLICT (customer_id, tool_size) DO NOTHING;

ALTER TABLE customers DROP COLUMN IF EXISTS work_rate_rub_per_hour;
ALTER TABLE customers DROP COLUMN IF EXISTS standby_rate_rub_per_day;

-- tool_revenue: work_hours -> work_qty (может быть и часами, и сутками —
-- в зависимости от work_unit), work_rate_rub_per_hour -> work_rate
-- (аналогично, единица берётся из work_unit), + новые колонки work_unit и
-- usage_hours (фактические часы, перенесённые в наработку инструмента).
ALTER TABLE tool_revenue RENAME COLUMN work_hours TO work_qty;
ALTER TABLE tool_revenue RENAME COLUMN work_rate_rub_per_hour TO work_rate;
ALTER TABLE tool_revenue ADD COLUMN IF NOT EXISTS work_unit TEXT NOT NULL DEFAULT 'hour';
ALTER TABLE tool_revenue ADD COLUMN IF NOT EXISTS usage_hours NUMERIC;

-- Для уже существующих записей выручки с заказчиком (все они были только
-- с почасовой ставкой — до этой миграции другой единицы не было)
-- фактические часы наработки совпадают с work_qty.
UPDATE tool_revenue SET usage_hours = work_qty WHERE usage_log_id IS NOT NULL AND usage_hours IS NULL;
