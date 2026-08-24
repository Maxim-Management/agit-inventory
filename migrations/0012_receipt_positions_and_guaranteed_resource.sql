-- Миграция 0012: реструктуризация поступлений (заказ -> позиции) и переход
-- на автоматический расчёт трансфер прайса по весу позиции.
--
-- Что меняется:
--   1. receipts.batch_serial_number удаляется — он просто дублировал
--      серийный номер конкретной единицы (units.serial_number). Партия
--      теперь идентифицируется парой order_ref + date_mfg (номер заказа +
--      дата производства).
--   2. Добавляются receipts.weight_kg (вес этой позиции), а также
--      order_total_weight_kg и order_total_shipping_cost_rub (общий вес
--      заказа и общие затраты на доставку заказа — вводятся один раз при
--      оформлении поступления и дублируются во все позиции этого заказа,
--      отдельной таблицы заказов не заводим). Из них трансфер прайс за
--      единицу позиции считается автоматически:
--        трансфер прайс позиции (итого) = order_total_shipping_cost_rub
--                                          × (weight_kg / order_total_weight_kg)
--        transfer_price_rub (за единицу) = трансфер прайс позиции (итого) / quantity
--      Сама формула стоимости за единицу (app/costing.py) не меняется —
--      transfer_price_rub как и раньше подставляется в неё за единицу.
--
-- "Гарантированный ресурс" компонента (средняя наработка на момент
-- списания по причине "ремонт") отдельного поля/таблицы не требует —
-- считается вживую по write_offs/units (см. app/stock.py:
-- guaranteed_resource_hours()), по аналогии с part_stock_value().

ALTER TABLE receipts ADD COLUMN IF NOT EXISTS weight_kg NUMERIC;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS order_total_weight_kg NUMERIC;
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS order_total_shipping_cost_rub NUMERIC;

ALTER TABLE receipts DROP COLUMN IF EXISTS batch_serial_number;
