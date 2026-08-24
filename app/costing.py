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
