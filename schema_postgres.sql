-- =====================================================================
-- Схема БД для сервиса контроля списания и остатков компонентов АГИТ
-- (осцилляторная система). Целевая СУБД: PostgreSQL (напр. Supabase).
-- Выполнить этот файл целиком в SQL Editor вашего проекта Supabase.
-- =====================================================================

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin', 'engineer', 'viewer')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS parts (
    id                     SERIAL PRIMARY KEY,
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
    is_serialized          BOOLEAN NOT NULL DEFAULT TRUE,
    -- Остаток "на начало" для несерийных (количественных) деталей — точка
    -- отсчёта, от которой далее прибавляются/вычитаются поступления и
    -- списания с датой ПОСЛЕ stock_baseline_date (см. app/stock.py).
    -- Для серийных деталей не используется — их остаток считается по
    -- статусам конкретных единиц (units).
    opening_balance_qty    NUMERIC NOT NULL DEFAULT 0,
    created_at             TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Реестр физических единиц инструмента (буровой компоновки) с собственным
-- серийным номером. Отличается от parts/units: parts/units — это
-- комплектующие ВНУТРИ инструмента (ротор, статор и т.п.), а tools — сам
-- инструмент как целое, на который эти комплектующие устанавливаются.
CREATE TABLE IF NOT EXISTS tools (
    id                SERIAL PRIMARY KEY,
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
    created_at        TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tools_serial ON tools(serial_number);

CREATE TABLE IF NOT EXISTS units (
    id                  SERIAL PRIMARY KEY,
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
    -- Партия поступления (receipts), в составе которой прибыла эта единица —
    -- FK добавляется ниже отдельным ALTER TABLE, т.к. receipts объявляется
    -- позже units в этом файле (см. комментарий у receipts). Используется
    -- для расчёта стоимости остатка по партиям (app/stock.py) и для
    -- автосвязывания списания серийного компонента с его партией.
    receipt_id          INTEGER,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (part_id, serial_number)
);
CREATE INDEX IF NOT EXISTS idx_units_part_status ON units(part_id, status);
CREATE INDEX IF NOT EXISTS idx_units_serial ON units(serial_number);
CREATE INDEX IF NOT EXISTS idx_units_tool ON units(installed_on_tool_id);
CREATE INDEX IF NOT EXISTS idx_units_receipt ON units(receipt_id);

CREATE TABLE IF NOT EXISTS receipts (
    id                    SERIAL PRIMARY KEY,
    part_id               INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    unit_id               INTEGER REFERENCES units(id) ON DELETE SET NULL,
    quantity              NUMERIC NOT NULL DEFAULT 1,
    receipt_date          DATE NOT NULL,
    order_ref             TEXT NOT NULL DEFAULT '',
    -- Таможенной пошлины здесь намеренно НЕТ — она привязана к позиции
    -- (parts.customs_duty_percent), а не к партии, см. комментарий у этого
    -- поля в таблице parts выше. Партия/поступление теперь идентифицируется
    -- парой order_ref + date_mfg (номер заказа + дата производства), а не
    -- отдельным номером партии — прежнее поле batch_serial_number удалено
    -- (миграция 0012), т.к. дублировало серийный номер единицы.
    date_mfg              TEXT NOT NULL DEFAULT '',
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
    -- Одна строка receipts = одна ПАРТИЯ поступления (для серийных деталей —
    -- сразу на все серийные номера, ввезённые вместе; для несерийных — как и
    -- раньше, одна поставка = одна строка). Остаток именно этой партии,
    -- ещё не списанный/использованный — стартует равным quantity и
    -- уменьшается при списании компонента ИЗ этой партии (см. app/stock.py и
    -- списание с выбором партии в app/routes_writeoffs.py / app/routes_jobs.py).
    remaining_quantity    NUMERIC NOT NULL DEFAULT 0,
    note                  TEXT NOT NULL DEFAULT '',
    created_by            INTEGER REFERENCES users(id),
    created_at            TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(receipt_date);
CREATE INDEX IF NOT EXISTS idx_receipts_part ON receipts(part_id);

ALTER TABLE units DROP CONSTRAINT IF EXISTS units_receipt_id_fkey;
ALTER TABLE units
    ADD CONSTRAINT units_receipt_id_fkey
    FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE SET NULL;

-- Ремонтные / сборочные работы — группируют списанные компоненты и прочие
-- затраты (сервисный центр, персонал, другое) для отчёта по стоимости работы.
CREATE TABLE IF NOT EXISTS service_jobs (
    id                    SERIAL PRIMARY KEY,
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
    created_at            TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_jobs_date ON service_jobs(job_date);
CREATE INDEX IF NOT EXISTS idx_jobs_tool ON service_jobs(tool_id);

CREATE TABLE IF NOT EXISTS write_offs (
    id             SERIAL PRIMARY KEY,
    part_id        INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    unit_id        INTEGER REFERENCES units(id) ON DELETE CASCADE,
    quantity       NUMERIC NOT NULL DEFAULT 1,
    write_off_date DATE NOT NULL,
    reason         TEXT NOT NULL CHECK (reason IN ('repair', 'defect', 'damage', 'other')),
    job_id         INTEGER REFERENCES service_jobs(id) ON DELETE SET NULL,
    -- Партия поступления, из которой фактически списан компонент — для
    -- серийных проставляется автоматически (по units.receipt_id снимаемой
    -- единицы), для несерийных выбирается пользователем на форме списания
    -- (см. «предлагать выбор из какой партии поступления списывать»).
    receipt_id     INTEGER REFERENCES receipts(id) ON DELETE SET NULL,
    act_number     TEXT NOT NULL DEFAULT '',
    note           TEXT NOT NULL DEFAULT '',
    created_by     INTEGER REFERENCES users(id),
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_writeoffs_date ON write_offs(write_off_date);
CREATE INDEX IF NOT EXISTS idx_writeoffs_unit ON write_offs(unit_id);
CREATE INDEX IF NOT EXISTS idx_writeoffs_part ON write_offs(part_id);
CREATE INDEX IF NOT EXISTS idx_writeoffs_job ON write_offs(job_id);
CREATE INDEX IF NOT EXISTS idx_writeoffs_receipt ON write_offs(receipt_id);

CREATE TABLE IF NOT EXISTS usage_logs (
    id                       SERIAL PRIMARY KEY,
    unit_id                  INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    log_date                 DATE NOT NULL,
    hours_added              NUMERIC NOT NULL DEFAULT 0,
    service_count_added      INTEGER NOT NULL DEFAULT 0,
    tool_assembly            TEXT NOT NULL DEFAULT '',
    note                     TEXT NOT NULL DEFAULT '',
    -- Если запись создана автоматически как зеркало наработки инструмента
    -- (см. tool_usage_logs ниже) — ссылка на исходную запись, чтобы при её
    -- редактировании/удалении можно было корректно пересчитать/удалить и
    -- эту зеркальную запись, и добавленные ею часы на units.circulation_hours.
    -- FK на tool_usage_logs добавляется ниже отдельным ALTER TABLE, т.к. эта
    -- таблица объявлена раньше, чем tool_usage_logs.
    source_tool_usage_log_id INTEGER,
    created_by               INTEGER REFERENCES users(id),
    created_at                TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_usagelogs_unit ON usage_logs(unit_id);

-- Наработка на уровне самого инструмента (буровой компоновки). Внесение
-- записи здесь автоматически создаёт зеркальные записи в usage_logs и
-- увеличивает circulation_hours для КАЖДОГО компонента (units), в данный
-- момент установленного на этом инструменте (units.installed_on_tool_id).
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

ALTER TABLE usage_logs
    DROP CONSTRAINT IF EXISTS usage_logs_source_tool_usage_log_id_fkey;
ALTER TABLE usage_logs
    ADD CONSTRAINT usage_logs_source_tool_usage_log_id_fkey
    FOREIGN KEY (source_tool_usage_log_id) REFERENCES tool_usage_logs(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_usagelogs_source_tool_log ON usage_logs(source_tool_usage_log_id);

-- Заказчики — справочник для внесения выручки: у каждого заказчика своя
-- ставка за час работы и за сутки ожидания/дежурства (см. tool_revenue
-- ниже — при выборе заказчика эти ставки подтягиваются автоматически и
-- сохраняются "снимком" на самой записи выручки, чтобы более позднее
-- изменение ставки в карточке заказчика не искажало задним числом уже
-- внесённую выручку).
CREATE TABLE IF NOT EXISTS customers (
    id                     SERIAL PRIMARY KEY,
    name                   TEXT NOT NULL,
    contract_number        TEXT NOT NULL DEFAULT '',
    note                   TEXT NOT NULL DEFAULT '',
    created_by             INTEGER REFERENCES users(id),
    created_at             TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name);

-- Ставки заказчика — отдельно по КАЖДОМУ типоразмеру инструмента (4 3/4",
-- 6 3/4", 8" — см. _TOOL_NAME_RULES в app/tools.py), т.к. стоимость работы и
-- дежурства у одного заказчика может отличаться в зависимости от размера
-- инструмента. У ставки "Работа" есть выбор единицы измерения — час или
-- сутки (work_rate_unit); ставка "Дежурство" всегда за сутки.
CREATE TABLE IF NOT EXISTS customer_rates (
    id                        SERIAL PRIMARY KEY,
    customer_id               INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    tool_size                 TEXT NOT NULL,
    work_rate                 NUMERIC NOT NULL DEFAULT 0,
    work_rate_unit            TEXT NOT NULL DEFAULT 'hour' CHECK (work_rate_unit IN ('hour', 'day')),
    standby_rate_rub_per_day  NUMERIC NOT NULL DEFAULT 0,
    UNIQUE (customer_id, tool_size)
);
CREATE INDEX IF NOT EXISTS idx_customerrates_customer ON customer_rates(customer_id);

-- Выручка, заработанная конкретным инструментом (по серийному номеру) —
-- используется для расчёта рентабельности (выручка минус (амортизация +
-- стоимость ремонтных/сборочных работ) по этому же инструменту).
-- Может вноситься вручную (amount заполнен напрямую, customer_id пуст —
-- прежний способ) либо через выбор заказчика: тогда well_number/work_qty/
-- standby_days вводятся на форме, ставка для типоразмера ЭТОГО инструмента
-- подтягивается из customer_rates и "замораживается" в work_rate/work_unit/
-- standby_rate_rub_per_day на этой же записи, amount считается автоматически
-- (work_qty * work_rate + standby_days * ставка_суток). Часы, переносимые в
-- наработку инструмента (usage_hours), — это ВСЕГДА часы: если work_unit =
-- 'hour', usage_hours = work_qty автоматически; если work_unit = 'day'
-- (ставка за сутки), work_qty суток само по себе не говорит, сколько часов
-- отработал инструмент, поэтому usage_hours в этом случае вводится отдельным
-- полем на форме. Перенесённая наработка создаёт запись tool_usage_logs, её
-- id сохраняется в usage_log_id — при удалении этой записи выручки
-- связанная наработка откатывается и удаляется, см. app/tools.py.
CREATE TABLE IF NOT EXISTS tool_revenue (
    id           SERIAL PRIMARY KEY,
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
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_toolrevenue_tool ON tool_revenue(tool_id);
CREATE INDEX IF NOT EXISTS idx_toolrevenue_customer ON tool_revenue(customer_id);

CREATE TABLE IF NOT EXISTS pairings (
    id              SERIAL PRIMARY KEY,
    rotor_unit_id   INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    stator_unit_id  INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    gap_mm          NUMERIC NOT NULL,
    status          TEXT NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested', 'confirmed', 'cancelled')),
    created_by      INTEGER REFERENCES users(id),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Первый администратор — email/пароль см. в README ("Первый запуск").
-- Пароль по умолчанию нужно сменить сразу после первого входа.
