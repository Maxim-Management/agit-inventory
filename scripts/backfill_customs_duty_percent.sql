-- Разовый скрипт: заполняет parts.customs_duty_percent (пошлина, %) для
-- деталей, у которых это поле сейчас пустое (NULL) — например, потому что
-- деталь была заведена в базу до того, как scripts/import_excel.py начал
-- переносить пошлину в карточку детали при повторном импорте (при повторном
-- запуске импорта для УЖЕ существующей детали её поля, включая пошлину, не
-- обновлялись — это отдельно исправлено в самом scripts/import_excel.py).
--
-- Значения взяты из исходного файла "AGIT Spares and Components.xlsx"
-- (лист "AGIT Spares", колонка "Tax, %") — по каждой детали пошлина
-- одинакова во всех её строках поступления в исходнике, поэтому конфликтов
-- нет.
--
-- Безопасно выполнять на любой базе (в т.ч. повторно) — каждая строка
-- обновляет пошлину ТОЛЬКО если сейчас она NULL, поэтому уже заполненные
-- вручную значения не затираются.
--
-- Запуск: выполните целиком в Supabase SQL Editor (или через
-- `sqlite3 data/agit.db < scripts/backfill_customs_duty_percent.sql` для
-- локальной SQLite-базы).

UPDATE parts SET customs_duty_percent = 7    WHERE part_number = '0203040006'  AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7    WHERE part_number = '203040001'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '203040010'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '203040011'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '203040012'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '203040014'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 0    WHERE part_number = '203040022'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 0    WHERE part_number = '203040024'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7    WHERE part_number = '203040025-29' AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7    WHERE part_number = '203040025-30' AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7    WHERE part_number = '203040025-31' AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 5    WHERE part_number = '207040001'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '207040003'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '207040005'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '207040006'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '207040007'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '207040008'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 38.5 WHERE part_number = '207040009'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '207040010'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '207040011'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '207040013'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '207040014'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '207040020'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 0    WHERE part_number = '442856664'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 5    WHERE part_number = '502010021'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 5    WHERE part_number = '502010032'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 5    WHERE part_number = '502010034'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 5    WHERE part_number = '502010059'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 5    WHERE part_number = '502020001'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 5    WHERE part_number = '502020004'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 5    WHERE part_number = '502020005'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 5    WHERE part_number = '502040004'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 7.5  WHERE part_number = '503010002'   AND customs_duty_percent IS NULL;
UPDATE parts SET customs_duty_percent = 15   WHERE part_number = '505020001'   AND customs_duty_percent IS NULL;
