-- =====================================================================
-- Миграция 0008: поступления как партии.
--
-- Одна строка receipts = одна ПАРТИЯ поступления (для серийных деталей —
-- сразу на все серийные номера, ввезённые вместе; для несерийных — как
-- и раньше, одна поставка = одна строка). У партии появляется остаток
-- (remaining_quantity), который расходуется списаниями ИЗ ЭТОЙ партии —
-- это и даёт возможность посчитать стоимость остатка по фактическим
-- партиям, и предложить выбор партии при списании.
--
-- Только структура (колонки/индексы/FK). Сам перенос существующих данных
-- (units.receipt_id ← receipts.unit_id, начальные remaining_quantity) —
-- отдельный одноразовый скрипт scripts/migrate_receipt_batches.py, его
-- нужно запустить СРАЗУ ПОСЛЕ этой миграции (см. README).
-- =====================================================================

ALTER TABLE units ADD COLUMN IF NOT EXISTS receipt_id INTEGER;
ALTER TABLE units DROP CONSTRAINT IF EXISTS units_receipt_id_fkey;
ALTER TABLE units
    ADD CONSTRAINT units_receipt_id_fkey
    FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_units_receipt ON units(receipt_id);

ALTER TABLE receipts ADD COLUMN IF NOT EXISTS remaining_quantity NUMERIC NOT NULL DEFAULT 0;

ALTER TABLE write_offs ADD COLUMN IF NOT EXISTS receipt_id INTEGER;
ALTER TABLE write_offs DROP CONSTRAINT IF EXISTS write_offs_receipt_id_fkey;
ALTER TABLE write_offs
    ADD CONSTRAINT write_offs_receipt_id_fkey
    FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_writeoffs_receipt ON write_offs(receipt_id);
