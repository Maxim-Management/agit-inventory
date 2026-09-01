-- =====================================================================
-- Миграция 0013: ремонт серийных компонентов (units) с указанием стоимости.
--
-- Новая таблица unit_repairs — запись о ремонте конкретной серийной единицы
-- (например, перемотка/переточка ротора или статора у стороннего
-- подрядчика). job_id опционален: запись можно создать саму по себе (просто
-- зафиксировать факт и стоимость ремонта), а можно сразу привязать к
-- ремонтной/сборочной работе (service_jobs) — тогда её стоимость (cost_rub)
-- учитывается в стоимости этой работы (см. app/jobs.py: job_totals(), поле
-- component_repairs_cost), то есть "ложится в стоимость ремонта инструмента"
-- при установке компонента в рамках этой работы (см. app/routes_units.py:
-- repair()). Выполнить в SQL Editor Supabase (PostgreSQL). Идемпотентна —
-- можно выполнять повторно.
-- =====================================================================

CREATE TABLE IF NOT EXISTS unit_repairs (
    id           SERIAL PRIMARY KEY,
    unit_id      INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    job_id       INTEGER REFERENCES service_jobs(id) ON DELETE SET NULL,
    repair_date  DATE NOT NULL,
    cost_rub     NUMERIC NOT NULL DEFAULT 0,
    note         TEXT NOT NULL DEFAULT '',
    created_by   INTEGER REFERENCES users(id),
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_unitrepairs_unit ON unit_repairs(unit_id);
CREATE INDEX IF NOT EXISTS idx_unitrepairs_job ON unit_repairs(job_id);
