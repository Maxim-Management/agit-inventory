-- =====================================================================
-- Миграция 0003: реестр инструментов (буровых компоновок) с серийными
-- номерами + привязка ремонтных/сборочных работ и установленных
-- компонентов к конкретному инструменту + наработка и выручка на уровне
-- инструмента.
--
-- Безопасно выполнять на уже развёрнутой базе (после schema_postgres.sql
-- + миграции 0002) — все операции идемпотентны (IF NOT EXISTS).
--
-- Выполните в SQL Editor вашего проекта Supabase.
-- =====================================================================

CREATE TABLE IF NOT EXISTS tools (
    id                SERIAL PRIMARY KEY,
    serial_number     TEXT NOT NULL UNIQUE,
    tool_size         TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'in_repair', 'retired')),
    commissioned_date DATE,
    location          TEXT NOT NULL DEFAULT '',
    note              TEXT NOT NULL DEFAULT '',
    created_by        INTEGER REFERENCES users(id),
    created_at        TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tools_serial ON tools(serial_number);

ALTER TABLE units ADD COLUMN IF NOT EXISTS installed_on_tool_id INTEGER REFERENCES tools(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_units_tool ON units(installed_on_tool_id);

ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS tool_id INTEGER REFERENCES tools(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_jobs_tool ON service_jobs(tool_id);

-- Наработка на уровне самого инструмента. Внесение записи здесь (через
-- app/tools.py -> log_tool_usage) автоматически создаёт зеркальные записи
-- в usage_logs и увеличивает circulation_hours для каждого компонента,
-- установленного на этом инструменте на момент записи.
CREATE TABLE IF NOT EXISTS tool_usage_logs (
    id           SERIAL PRIMARY KEY,
    tool_id      INTEGER NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    log_date     DATE NOT NULL,
    hours_added  NUMERIC NOT NULL DEFAULT 0,
    note         TEXT NOT NULL DEFAULT '',
    created_by   INTEGER REFERENCES users(id),
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_toolusagelogs_tool ON tool_usage_logs(tool_id);

CREATE TABLE IF NOT EXISTS tool_revenue (
    id           SERIAL PRIMARY KEY,
    tool_id      INTEGER NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    revenue_date DATE NOT NULL,
    amount       NUMERIC NOT NULL DEFAULT 0,
    currency     TEXT NOT NULL DEFAULT 'RUB',
    note         TEXT NOT NULL DEFAULT '',
    created_by   INTEGER REFERENCES users(id),
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_toolrevenue_tool ON tool_revenue(tool_id);

-- Если у вас уже есть данные об "Installed on tool" в исходном Excel,
-- перезапустите scripts/import_excel.py — он идемпотентен и создаст
-- записи в tools + проставит units.installed_on_tool_id.
