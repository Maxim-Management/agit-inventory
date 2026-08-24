-- =====================================================================
-- Миграция 0002: единый учёт остатков для всех деталей (включая
-- несерийные расходники — масло, уплотнения и т.п.) + ремонтные/сборочные
-- работы с отчётом по затратам.
--
-- Безопасно выполнять и на уже развёрнутой базе (после schema_postgres.sql
-- из первой версии), и сразу после актуального schema_postgres.sql — все
-- операции идемпотентны (IF NOT EXISTS / проверка на существование).
--
-- Выполните в SQL Editor вашего проекта Supabase.
-- =====================================================================

ALTER TABLE parts ADD COLUMN IF NOT EXISTS unit_transfer_price_rub NUMERIC;
ALTER TABLE parts ADD COLUMN IF NOT EXISTS opening_balance_qty NUMERIC NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS service_jobs (
    id                    SERIAL PRIMARY KEY,
    job_type              TEXT NOT NULL DEFAULT 'repair' CHECK (job_type IN ('repair', 'assembly', 'other')),
    job_date              DATE NOT NULL,
    tool_assembly         TEXT NOT NULL DEFAULT '',
    title                 TEXT NOT NULL DEFAULT '',
    service_center_cost   NUMERIC NOT NULL DEFAULT 0,
    labor_cost            NUMERIC NOT NULL DEFAULT 0,
    other_cost            NUMERIC NOT NULL DEFAULT 0,
    currency              TEXT NOT NULL DEFAULT 'RUB',
    note                  TEXT NOT NULL DEFAULT '',
    created_by            INTEGER REFERENCES users(id),
    created_at            TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_jobs_date ON service_jobs(job_date);

-- write_offs раньше был жёстко привязан к серийной единице (unit_id NOT NULL).
-- Теперь запись о списании всегда ссылается на деталь (part_id), а unit_id
-- заполняется только для серийных компонентов; добавлены quantity (для
-- несерийных расходников) и job_id (привязка к ремонтной/сборочной работе).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'write_offs' AND column_name = 'part_id') THEN
        ALTER TABLE write_offs ADD COLUMN part_id INTEGER REFERENCES parts(id) ON DELETE CASCADE;
        UPDATE write_offs w SET part_id = u.part_id FROM units u WHERE u.id = w.unit_id;
        ALTER TABLE write_offs ALTER COLUMN part_id SET NOT NULL;
    END IF;
END $$;

ALTER TABLE write_offs ADD COLUMN IF NOT EXISTS quantity NUMERIC NOT NULL DEFAULT 1;
ALTER TABLE write_offs ADD COLUMN IF NOT EXISTS job_id INTEGER REFERENCES service_jobs(id) ON DELETE SET NULL;
ALTER TABLE write_offs ALTER COLUMN unit_id DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_writeoffs_part ON write_offs(part_id);
CREATE INDEX IF NOT EXISTS idx_writeoffs_job ON write_offs(job_id);

-- Если у вас уже был запущен импорт из Excel по предыдущей версии схемы,
-- перезапустите scripts/import_excel.py — он идемпотентен (пропускает уже
-- существующие детали/единицы) и дозаполнит unit_transfer_price_rub и
-- opening_balance_qty для несерийных деталей.
