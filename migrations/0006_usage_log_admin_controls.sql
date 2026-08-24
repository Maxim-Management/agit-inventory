-- =====================================================================
-- Миграция 0006: возможность редактирования/удаления ремонтных работ,
-- записей наработки и выручки — доступно только администратору.
--
-- Для корректного удаления/редактирования наработки инструмента (когда
-- запись наработки инструмента зеркально прибавляет часы всем установленным
-- на нём компонентам) добавлена ссылка usage_logs.source_tool_usage_log_id
-- на исходную запись в tool_usage_logs — по ней приложение находит и
-- пересчитывает/удаляет зеркальные записи и корректирует
-- units.circulation_hours.
--
-- Безопасно выполнять на уже развёрнутой базе — все операции идемпотентны.
-- Выполните в SQL Editor вашего проекта Supabase.
-- =====================================================================

ALTER TABLE usage_logs ADD COLUMN IF NOT EXISTS source_tool_usage_log_id INTEGER;

ALTER TABLE usage_logs
    DROP CONSTRAINT IF EXISTS usage_logs_source_tool_usage_log_id_fkey;
ALTER TABLE usage_logs
    ADD CONSTRAINT usage_logs_source_tool_usage_log_id_fkey
    FOREIGN KEY (source_tool_usage_log_id) REFERENCES tool_usage_logs(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_usagelogs_source_tool_log ON usage_logs(source_tool_usage_log_id);
