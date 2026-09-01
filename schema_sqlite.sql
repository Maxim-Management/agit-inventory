-- =====================================================================
-- Та же схема, адаптированная под SQLite — используется только для
-- локальной разработки/демонстрации (см. scripts/init_db.py).
-- В продакшне используется schema_postgres.sql (Supabase/PostgreSQL).
-- =====================================================================

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin', 'engineer', 'viewer')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parts (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_size              TEXT NOT NULL DEFAULT '',
    part_name              TEXT NOT NULL,
    part_number            TEXT NOT NULL UNIQUE,
    category               TEXT NOT NULL DEFAULT 'other' CHECK (category IN ('rotor', 'stator', 'other')),
    specification          TEXT NOT NULL DEFAULT '',
    unit_weight_kg         NUMERIC,
    -- Составляющие расчётной стоимости за единицу (см. app/costing.py):
    -- стоимость = standard_cost_cny * exchange_rate * (1 + customs_duty_percent/100)
    --             + unit_transfer_price_rub.
    -- standard_cost_cny / exchange_rate / unit_transfer_price_rub кэшируют
    -- данные САМОГО ПОСЛЕДНЕГО поступления по этой детали (себестоимость
    -- может отличаться от партии к партии) — обновляются автоматически при
    -- регистрации нового поступления (см. routes_receipts.py), либо правятся
    -- вручную в карточке детали. customs_duty_percent — ИСКЛЮЧЕНИЕ: это
    -- атрибут самой позиции (part_number), а не партии — таможенная пошлина
    -- одна и та же для всех поступлений этой детали независимо от партии, и
    -- меняется только вручную в карточке детали (поступления её не трогают).
    standard_cost_cny      NUMERIC,
    exchange_rate          NUMERIC,
    customs_duty_percent   NUMERIC,
    unit_transfer_price_rub NUMERIC,
    min_stock_qty          INTEGER NOT NULL DEFAULT 0,
    is_serialized          INTEGER NOT NULL DEFAULT 1,
    opening_balance_qty    NUMERIC NOT NULL DEFAULT 0,
    created_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tools (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    serial_number     TEXT NOT NULL UNIQUE,
    tool_size         TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'in_repair', 'retired')),
    commissioned_date DATE,
    -- Себестоимость инструмента, ₽ — база для расчёта начисленной
    -- амортизации (1/18 стоимости в месяц с даты ввода в эксплуатацию,
    -- см. app/tools.py: tool_depreciation()).
    cost_rub          NUMERIC,
    location          TEXT NOT NULL DEFAULT '',
    note              TEXT NOT NULL DEFAULT '',
    created_by        INTEGER REFERENCES users(id),
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tools_serial ON tools(serial_number);

CREATE TABLE IF NOT EXISTS units (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id             INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    serial_number       TEXT NOT NULL,
    date_mfg            TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'in_stock' CHECK (status IN ('in_stock', 'installed', 'paired', 'written_off')),
    installed_on        TEXT NOT NULL DEFAULT '',
    installed_on_tool_id INTEGER REFERENCES tools(id) ON DELETE SET NULL,
    circulation_hours   NUMERIC NOT NULL DEFAULT 0,
    service_count       INTEGER NOT NULL DEFAULT 0,
    od_mm               NUMERIC,
    id_mm               NUMERIC,
    location            TEXT NOT NULL DEFAULT '',
    remarks             TEXT NOT NULL DEFAULT '',
    paired_with_unit_id INTEGER REFERENCES units(id) ON DELETE SET NULL,
    receipt_id          INTEGER REFERENCES receipts(id) ON DELETE SET NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (part_id, serial_number)
);
CREATE INDEX IF NOT EXISTS idx_units_part_status ON units(part_id, status);
CREATE INDEX IF NOT EXISTS idx_units_serial ON units(serial_number);
CREATE INDEX IF NOT EXISTS idx_units_tool ON units(installed_on_tool_id);
CREATE INDEX IF NOT EXISTS idx_units_receipt ON units(receipt_id);

CREATE TABLE IF NOT EXISTS receipts (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id               INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    unit_id               INTEGER REFERENCES units(id) ON DELETE SET NULL,
    quantity              NUMERIC NOT NULL DEFAULT 1,
    receipt_date          DATE NOT NULL,
    order_ref             TEXT NOT NULL DEFAULT '',
    date_mfg              TEXT NOT NULL DEFAULT '',
    -- Таможенной пошлины здесь намеренно НЕТ — она привязана к позиции
    -- (parts.customs_duty_percent), а не к партии, см. комментарий у этого
    -- поля в таблице parts выше. Партия/поступление теперь идентифицируется
    -- парой order_ref + date_mfg (номер заказа + дата производства), а не
    -- отдельным номером партии — прежнее поле batch_serial_number удалено
    -- (миграция 0012), т.к. дублировало серийный номер единицы.
    exchange_rate         NUMERIC,
    total_cost_cny        NUMERIC,
    -- Вес этой позиции (строки поступления), кг — вводится вручную (общий
    -- вес по факту, с коробки/накладной), а не берётся из карточки детали.
    -- Вместе с order_total_weight_kg/order_total_shipping_cost_rub этого же
    -- заказа используется для автоматического расчёта трансфер прайса
    -- (см. app/routes_receipts.py: транспорт прайс позиции = общие затраты
    -- на доставку заказа × (вес позиции / общий вес заказа), далее — за
    -- единицу этой позиции). order_total_weight_kg и
    -- order_total_shipping_cost_rub дублируются в каждую позицию одного
    -- заказа (справочно/для аудита расчёта, отдельной таблицы заказов нет).
    weight_kg                     NUMERIC,
    order_total_weight_kg         NUMERIC,
    order_total_shipping_cost_rub NUMERIC,
    -- Трансфер прайс за единицу в этой партии, ₽ (логистика/доставка сверх
    -- таможенной стоимости) — вместе с total_cost_cny/quantity, exchange_rate
    -- партии и customs_duty_percent детали участвует в формуле стоимости
    -- единицы (см. app/costing.py). При сохранении поступления актуализирует
    -- соответствующие поля в карточке детали (parts). Рассчитывается
    -- автоматически из weight_kg/order_total_weight_kg/
    -- order_total_shipping_cost_rub (см. выше), но хранится явно, т.к. это
    -- ЕДИНСТВЕННОЕ значение, которое реально участвует в формуле стоимости
    -- единицы (app/costing.py) — вес и итоговые суммы заказа в ней не
    -- используются напрямую.
    transfer_price_rub    NUMERIC,
    remaining_quantity    NUMERIC NOT NULL DEFAULT 0,
    note                  TEXT NOT NULL DEFAULT '',
    created_by            INTEGER REFERENCES users(id),
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(receipt_date);
CREATE INDEX IF NOT EXISTS idx_receipts_part ON receipts(part_id);

CREATE TABLE IF NOT EXISTS service_jobs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type              TEXT NOT NULL DEFAULT 'repair' CHECK (job_type IN ('repair', 'assembly', 'other')),
    job_date              DATE NOT NULL,
    tool_id               INTEGER REFERENCES tools(id) ON DELETE SET NULL,
    tool_assembly         TEXT NOT NULL DEFAULT '',
    title                 TEXT NOT NULL DEFAULT '',
    work_order_number     TEXT NOT NULL DEFAULT '',
    performed_by          TEXT NOT NULL DEFAULT '',
    service_center        TEXT NOT NULL DEFAULT '',
    service_center_cost   NUMERIC NOT NULL DEFAULT 0,
    labor_cost            NUMERIC NOT NULL DEFAULT 0,
    other_cost            NUMERIC NOT NULL DEFAULT 0,
    currency              TEXT NOT NULL DEFAULT 'RUB',
    note                  TEXT NOT NULL DEFAULT '',
    created_by            INTEGER REFERENCES users(id),
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_jobs_date ON service_jobs(job_date);
CREATE INDEX IF NOT EXISTS idx_jobs_tool ON service_jobs(tool_id);

CREATE TABLE IF NOT EXISTS write_offs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id        INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    unit_id        INTEGER REFERENCES units(id) ON DELETE CASCADE,
    quantity       NUMERIC NOT NULL DEFAULT 1,
    write_off_date DATE NOT NULL,
    reason         TEXT NOT NULL CHECK (reason IN ('repair', 'defect', 'damage', 'other')),
    job_id         INTEGER REFERENCES service_jobs(id) ON DELETE SET NULL,
    receipt_id     INTEGER REFERENCES receipts(id) ON DELETE SET NULL,
    act_number     TEXT NOT NULL DEFAULT '',
    note           TEXT NOT NULL DEFAULT '',
    created_by     INTEGER REFERENCES users(id),
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_writeoffs_date ON write_offs(write_off_date);
CREATE INDEX IF NOT EXISTS idx_writeoffs_unit ON write_offs(unit_id);
CREATE INDEX IF NOT EXISTS idx_writeoffs_part ON write_offs(part_id);
CREATE INDEX IF NOT EXISTS idx_writeoffs_job ON write_offs(job_id);
CREATE INDEX IF NOT EXISTS idx_writeoffs_receipt ON write_offs(receipt_id);

CREATE TABLE IF NOT EXISTS usage_logs (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id                  INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    log_date                 DATE NOT NULL,
    hours_added              NUMERIC NOT NULL DEFAULT 0,
    service_count_added      INTEGER NOT NULL DEFAULT 0,
    tool_assembly            TEXT NOT NULL DEFAULT '',
    note                     TEXT NOT NULL DEFAULT '',
    source_tool_usage_log_id INTEGER REFERENCES tool_usage_logs(id) ON DELETE CASCADE,
    created_by               INTEGER REFERENCES users(id),
    created_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_usagelogs_unit ON usage_logs(unit_id);

CREATE TABLE IF NOT EXISTS tool_usage_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_id      INTEGER NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    log_date     DATE NOT NULL,
    hours_added  NUMERIC NOT NULL DEFAULT 0,
    note         TEXT NOT NULL DEFAULT '',
    created_by   INTEGER REFERENCES users(id),
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_toolusagelogs_tool ON tool_usage_logs(tool_id);

CREATE TABLE IF NOT EXISTS unit_repairs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id      INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    job_id       INTEGER REFERENCES service_jobs(id) ON DELETE SET NULL,
    repair_date  DATE NOT NULL,
    cost_rub     NUMERIC NOT NULL DEFAULT 0,
    note         TEXT NOT NULL DEFAULT '',
    created_by   INTEGER REFERENCES users(id),
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_unitrepairs_unit ON unit_repairs(unit_id);
CREATE INDEX IF NOT EXISTS idx_unitrepairs_job ON unit_repairs(job_id);

CREATE TABLE IF NOT EXISTS customers (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    name                   TEXT NOT NULL,
    contract_number        TEXT NOT NULL DEFAULT '',
    note                   TEXT NOT NULL DEFAULT '',
    created_by             INTEGER REFERENCES users(id),
    created_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name);

CREATE TABLE IF NOT EXISTS customer_rates (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id               INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    tool_size                 TEXT NOT NULL,
    work_rate                 NUMERIC NOT NULL DEFAULT 0,
    work_rate_unit            TEXT NOT NULL DEFAULT 'hour' CHECK (work_rate_unit IN ('hour', 'day')),
    standby_rate_rub_per_day  NUMERIC NOT NULL DEFAULT 0,
    UNIQUE (customer_id, tool_size)
);
CREATE INDEX IF NOT EXISTS idx_customerrates_customer ON customer_rates(customer_id);

CREATE TABLE IF NOT EXISTS tool_revenue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_id      INTEGER NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    revenue_date DATE NOT NULL,
    amount       NUMERIC NOT NULL DEFAULT 0,
    currency     TEXT NOT NULL DEFAULT 'RUB',
    note         TEXT NOT NULL DEFAULT '',
    customer_id  INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    well_number  TEXT NOT NULL DEFAULT '',
    work_qty     NUMERIC,
    work_unit    TEXT NOT NULL DEFAULT 'hour' CHECK (work_unit IN ('hour', 'day')),
    standby_days NUMERIC,
    work_rate                NUMERIC,
    standby_rate_rub_per_day NUMERIC,
    usage_hours  NUMERIC,
    usage_log_id INTEGER REFERENCES tool_usage_logs(id) ON DELETE SET NULL,
    created_by   INTEGER REFERENCES users(id),
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_toolrevenue_tool ON tool_revenue(tool_id);
CREATE INDEX IF NOT EXISTS idx_toolrevenue_customer ON tool_revenue(customer_id);

CREATE TABLE IF NOT EXISTS pairings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rotor_unit_id   INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    stator_unit_id  INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    gap_mm          NUMERIC NOT NULL,
    status          TEXT NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested', 'confirmed', 'cancelled')),
    created_by      INTEGER REFERENCES users(id),
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
