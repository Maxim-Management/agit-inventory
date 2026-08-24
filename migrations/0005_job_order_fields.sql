-- =====================================================================
-- Миграция 0005: новые поля ремонтной/сборочной работы — номер
-- наряд-заказа, исполнитель (супервайзер), наименование сервисного
-- центра (отдельно от уже существующей стоимости услуг сервисного
-- центра service_center_cost).
--
-- Безопасно выполнять на уже развёрнутой базе — все операции идемпотентны.
-- Выполните в SQL Editor вашего проекта Supabase.
-- =====================================================================

ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS work_order_number TEXT NOT NULL DEFAULT '';
ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS performed_by TEXT NOT NULL DEFAULT '';
ALTER TABLE service_jobs ADD COLUMN IF NOT EXISTS service_center TEXT NOT NULL DEFAULT '';
