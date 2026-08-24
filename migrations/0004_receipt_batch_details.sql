-- =====================================================================
-- Миграция 0004: детали партии поступления — серийный номер по строке
-- партии, дата производства, таможенная пошлина (%), курс валюты на
-- момент покупки, общая стоимость партии в CNY. Заполняются при импорте
-- из листа "AGIT Spares" исходного Excel-файла (см. scripts/import_excel.py)
-- и опционально при ручном добавлении поступления через интерфейс.
--
-- Безопасно выполнять на уже развёрнутой базе — все операции идемпотентны.
-- Выполните в SQL Editor вашего проекта Supabase.
-- =====================================================================

ALTER TABLE receipts ADD COLUMN IF NOT EXISTS batch_serial_number TEXT NOT NULL DEFAULT '';
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS date_mfg TEXT NOT NULL DEFAULT '';
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS customs_duty_percent NUMERIC;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS total_cost_cny NUMERIC;

-- Если импорт из Excel уже запускался по предыдущей версии схемы,
-- перезапустите scripts/import_excel.py — он идемпотентен (не создаёт
-- дублей уже существующих деталей/единиц/поступлений) и для новых партий
-- дозаполнит эти поля. Уже существующие строки поступлений эта миграция
-- не меняет — их можно оставить как есть (поля просто останутся пустыми)
-- либо переимпортировать с нуля на чистой базе, если это некритично.
