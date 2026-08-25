"""Формула расчётной стоимости за единицу.

Стоимость единицы, ₽ = себестоимость, CNY × курс юаня к рублю ×
                        (1 + пошлина, % / 100) + трансфер прайс, ₽.

Курс — всегда курс юаня (CNY) к рублю (RUB), как и было в поступлениях;
трансфер прайс — за единицу, в рублях. Используется и для "текущей"
стоимости в карточке детали (app/routes_parts.py), и для стоимости
конкретной партии поступления (app/routes_receipts.py), и для стоимости
списанных на ремонтную работу компонентов (app/jobs.py) — везде одна и
та же функция, чтобы формула не разъезжалась по местам.
"""


def unit_cost_rub(cost_cny, exchange_rate, customs_duty_percent, transfer_price_rub):
    """Считает стоимость одной единицы в рублях по формуле. Отсутствующие
    (None) компоненты формулы считаются нулевыми — так расчёт не падает и
    не блокирует ввод данных, если часть полей ещё не заполнена, но при
    этом честно показывает частичную сумму (например, один трансфер прайс,
    если себестоимость в юанях ещё не внесена)."""
    cny = float(cost_cny) if cost_cny is not None else 0.0
    rate = float(exchange_rate) if exchange_rate is not None else 0.0
    duty_factor = 1.0 + (float(customs_duty_percent) / 100.0 if customs_duty_percent is not None else 0.0)
    transfer = float(transfer_price_rub) if transfer_price_rub is not None else 0.0
    return cny * rate * duty_factor + transfer


def part_unit_cost_rub(part):
    """Удобная обёртка: считает стоимость единицы по 4 полям детали
    (parts.standard_cost_cny/exchange_rate/customs_duty_percent/
    unit_transfer_price_rub) — их "текущим" (последнего поступления)
    значениям, кэшированным в карточке детали."""
    return unit_cost_rub(
        part.get("standard_cost_cny"),
        part.get("exchange_rate"),
        part.get("customs_duty_percent"),
        part.get("unit_transfer_price_rub"),
    )


def write_off_unit_cost_rub(row):
    """Стоимость СПИСАННОЙ единицы, ₽ — по факту той конкретной ПАРТИИ
    (receipts), из которой она была списана (write_offs.receipt_id), а не
    по "текущим" (последнего поступления) значениям карточки детали:
    себестоимость в CNY, курс юаня и трансфер прайс могут отличаться от
    партии к партии (например, единица списана сейчас, но была получена
    полгода назад по другому курсу) — именно так уже считается стоимость
    ОСТАТКА (app/stock.py: part_stock_value), поэтому стоимость списания
    считается тем же способом, для согласованности.

    Пошлина всегда берётся из карточки детали (parts.customs_duty_percent) —
    она едина для всех партий этой позиции, не хранится отдельно по партиям.

    Если у списания нет привязанной партии (receipt_id NULL — например,
    более старые записи, сделанные до появления этой связи, или расходник
    списан, когда открытых партий с остатком уже не было) — используется
    запасной вариант: "текущие" значения карточки детали, как считалось
    раньше (см. part_unit_cost_rub).

    Ожидает строку с полями партии (receipt_total_cost_cny, receipt_quantity,
    receipt_exchange_rate, receipt_transfer_price_rub) и детали
    (customs_duty_percent, part_standard_cost_cny, part_exchange_rate,
    part_unit_transfer_price_rub) — см. app/jobs.py: job_write_offs()."""
    receipt_qty = float(row["receipt_quantity"]) if row.get("receipt_quantity") is not None else None
    receipt_total_cny = float(row["receipt_total_cost_cny"]) if row.get("receipt_total_cost_cny") is not None else None
    cost_cny_per_unit = (receipt_total_cny / receipt_qty) if (receipt_total_cny is not None and receipt_qty) \
        else row.get("part_standard_cost_cny")
    exchange_rate = row["receipt_exchange_rate"] if row.get("receipt_exchange_rate") is not None \
        else row.get("part_exchange_rate")
    transfer_price = row["receipt_transfer_price_rub"] if row.get("receipt_transfer_price_rub") is not None \
        else row.get("part_unit_transfer_price_rub")
    return unit_cost_rub(cost_cny_per_unit, exchange_rate, row.get("customs_duty_percent"), transfer_price)
