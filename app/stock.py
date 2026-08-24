"""
Единый расчёт текущего остатка для ЛЮБОЙ детали — серийной (ротор, статор,
корпусные детали и т.п.) или несерийной/расходной (масло, уплотнения,
кольца и т.п.). Используется дэшбордом, справочником деталей, аналитикой
и прогнозом заказа — все они видят один и тот же остаток по каждой детали.

Логика:
  - Серийные детали (parts.is_serialized = true): остаток = количество
    единиц (units) в статусе 'in_stock'. Источник истины — карточки
    конкретных серийных компонентов.
  - Несерийные детали: остаток = "остаток на начало" (parts.opening_balance_qty,
    зафиксирован при первом импорте данных из Excel) + сумма поступлений
    (receipts) с датой ПОСЛЕ даты среза STOCK_BASELINE_DATE − сумма
    списаний (write_offs, не привязанных к конкретной единице) с датой
    после той же даты среза.

    Дата среза нужна, чтобы не задвоить исторические поступления, уже
    учтённые в "остатке на начало" при импорте (см. scripts/import_excel.py).
    Все операции, вносимые через само приложение после начала эксплуатации,
    естественным образом попадают в диапазон "после даты среза" и корректно
    прибавляются/вычитаются.
"""
from datetime import date

from . import db
from .costing import unit_cost_rub

# Дата среза должна ТОЧНО совпадать с датой самого позднего исторического
# поступления, импортированного скриптом scripts/import_excel.py (сейчас —
# 2026-08-01, см. RECEIPT_COLUMNS там). Формула ниже использует "> дата
# среза" (строго позже), поэтому:
#   - импортированные исторические поступления (датированные <= среза)
#     корректно исключаются, т.к. уже учтены в opening_balance_qty;
#   - любая операция, вносимая через само приложение ПОСЛЕ среза (в т.ч.
#     "сегодня", когда бы оно ни наступило), корректно попадает в расчёт.
# Намеренно НЕ ставьте эту дату близко к "сегодня" — иначе операции,
# внесённые в первые дни эксплуатации, будут молча проигнорированы.
STOCK_BASELINE_DATE = date(2026, 8, 1)


def stock_map():
    """Возвращает {part_id: текущий_остаток} для всех деталей одним проходом."""
    serialized_rows = db.query_all(
        "SELECT part_id, COUNT(*) AS cnt FROM units WHERE status = 'in_stock' GROUP BY part_id"
    )
    serialized_stock = {r["part_id"]: r["cnt"] for r in serialized_rows}

    receipts_rows = db.query_all(
        "SELECT part_id, COALESCE(SUM(quantity),0) AS s FROM receipts WHERE receipt_date > %s GROUP BY part_id",
        [STOCK_BASELINE_DATE.isoformat()],
    )
    receipts_after = {r["part_id"]: float(r["s"]) for r in receipts_rows}

    writeoffs_rows = db.query_all(
        """SELECT part_id, COALESCE(SUM(quantity),0) AS s FROM write_offs
           WHERE unit_id IS NULL AND write_off_date > %s GROUP BY part_id""",
        [STOCK_BASELINE_DATE.isoformat()],
    )
    writeoffs_after = {r["part_id"]: float(r["s"]) for r in writeoffs_rows}

    parts = db.query_all("SELECT id, is_serialized, opening_balance_qty FROM parts")

    result = {}
    for p in parts:
        pid = p["id"]
        if p["is_serialized"]:
            result[pid] = serialized_stock.get(pid, 0)
        else:
            opening = float(p["opening_balance_qty"] or 0)
            result[pid] = opening + receipts_after.get(pid, 0.0) - writeoffs_after.get(pid, 0.0)
    return result


def current_stock_for_part(part_id):
    return stock_map().get(part_id, 0)


# ---------------------------------------------------------------------------
# Партии поступления (receipts как «партия», см. миграцию 0008) — остаток
# партии (receipts.remaining_quantity), выбор партии при списании и оценка
# стоимости остатка по фактическим партиям, из которых он состоит.
# ---------------------------------------------------------------------------

def open_batches_for_part(part_id):
    """Партии этой детали, из которых ещё есть что списывать (остаток > 0),
    от старой к новой — используется для выбора партии при списании
    (по умолчанию предлагается самая старая, как при обычном FIFO).
    Таможенная пошлина берётся из карточки детали (parts.customs_duty_percent),
    а не из партии — она одна и та же для всех партий этой позиции."""
    return db.query_all(
        """SELECT r.id, r.order_ref, r.date_mfg, r.receipt_date, r.quantity, r.remaining_quantity,
                  r.exchange_rate, p.customs_duty_percent, r.total_cost_cny, r.transfer_price_rub
           FROM receipts r JOIN parts p ON p.id = r.part_id
           WHERE r.part_id = %s AND r.remaining_quantity > 0
           ORDER BY r.receipt_date, r.id""",
        [part_id],
    )


def batch_label(b):
    """Читаемая метка партии для выпадающих списков при списании — партия
    больше не имеет отдельного номера (см. миграцию 0012), поэтому
    идентифицируется номером заказа и датой производства; если ни того, ни
    другого нет — запасной вариант "партия #id"."""
    parts_ = [p for p in [b.get("order_ref"), b.get("date_mfg")] if p]
    return " / ".join(parts_) if parts_ else ("партия #" + str(b["id"]))


def consume_from_batch(receipt_id, qty):
    """Списывает qty из остатка партии (не уводит остаток партии в минус —
    если запрошено больше, чем реально осталось, списывает сколько есть).
    Возвращает фактически списанное количество."""
    if not receipt_id or not qty:
        return 0.0
    r = db.query_one("SELECT remaining_quantity FROM receipts WHERE id = %s", [receipt_id])
    if not r:
        return 0.0
    current = float(r["remaining_quantity"] or 0)
    consumed = min(current, float(qty))
    if consumed <= 0:
        return 0.0
    db.execute("UPDATE receipts SET remaining_quantity = %s WHERE id = %s", [current - consumed, receipt_id])
    return consumed


def restore_to_batch(receipt_id, qty):
    """Возвращает qty в остаток партии (отмена списания / удаление работы)."""
    if not receipt_id or not qty:
        return
    db.execute("UPDATE receipts SET remaining_quantity = remaining_quantity + %s WHERE id = %s", [qty, receipt_id])


def part_stock_value(part_id):
    """Стоимость остатка детали, ₽ — сумма по ВСЕМ партиям с остатком > 0:
    (стоимость за единицу этой партии) × (остаток именно этой партии).
    Курс юаня — средневзвешенный по остатку (партии с бОльшим остатком
    сильнее влияют на средний курс), не по количеству партий."""
    batches = open_batches_for_part(part_id)
    total_value = 0.0
    total_qty = 0.0
    weighted_rate_sum = 0.0
    priced_qty = 0.0
    for b in batches:
        remaining = float(b["remaining_quantity"] or 0)
        if remaining <= 0:
            continue
        qty = float(b["quantity"] or 0)
        total_cost_cny = float(b["total_cost_cny"]) if b.get("total_cost_cny") is not None else None
        cny_per_unit = (total_cost_cny / qty) if (total_cost_cny is not None and qty) else total_cost_cny
        unit_cost = unit_cost_rub(cny_per_unit, b["exchange_rate"], b["customs_duty_percent"], b.get("transfer_price_rub"))
        total_value += unit_cost * remaining
        total_qty += remaining
        if b["exchange_rate"] is not None:
            weighted_rate_sum += float(b["exchange_rate"]) * remaining
            priced_qty += remaining
    avg_exchange_rate = (weighted_rate_sum / priced_qty) if priced_qty else None
    return {
        "stock_value_rub": round(total_value, 2),
        "avg_exchange_rate": avg_exchange_rate,
        "valued_qty": total_qty,
    }


def total_stock_value():
    """Суммарная стоимость остатка комплектующих по всему складу, ₽
    (сумма part_stock_value() по всем деталям) — для дэшборда."""
    part_ids = [r["id"] for r in db.query_all("SELECT id FROM parts")]
    return round(sum(part_stock_value(pid)["stock_value_rub"] for pid in part_ids), 2)


def avg_exchange_rate_all_receipts(part_id):
    """Простой (не взвешенный по количеству) средний курс юаня к рублю по
    ВСЕМ когда-либо зарегистрированным поступлениям этой детали — только
    справочная информация в карточке детали, рядом с расчётом «Стоимость за
    единицу». В самом расчёте («Стоимость за единицу» / стоимость списаний
    на ремонт) НЕ участвует — там по-прежнему используется «текущий» курс
    из карточки детали (parts.exchange_rate, обновляется последним
    поступлением), см. app/costing.py. Возвращает None, если у детали ещё
    нет ни одного поступления с указанным курсом."""
    row = db.query_one(
        "SELECT AVG(exchange_rate) AS avg_rate, COUNT(exchange_rate) AS cnt "
        "FROM receipts WHERE part_id = %s AND exchange_rate IS NOT NULL",
        [part_id],
    )
    if not row or not row["cnt"]:
        return None
    return float(row["avg_rate"])


def guaranteed_resource_hours(part_id):
    """"Гарантированный ресурс" компонента, ч — сколько наработки в среднем
    выдерживает деталь до списания по износу/выходу из строя. Считается
    вживую (по аналогии с part_stock_value) как средняя наработка
    (units.circulation_hours) на момент списания среди списаний ЭТОЙ детали
    с причиной "ремонт" (write_offs.reason = 'repair') — то есть именно
    ремонт по факту износа/поломки, а не заводской брак ('defect') или
    механическое повреждение ('damage'). Наработка серийной единицы после
    списания больше не меняется (единица снята с эксплуатации), поэтому
    circulation_hours на этот момент и есть её "стаж" до выбытия.
    Возвращает None, если по этой детали ещё не было ни одного такого
    списания серийной единицы (для несерийных расходников понятие
    "гарантированного ресурса" неприменимо — там нет units.circulation_hours)."""
    row = db.query_one(
        """SELECT AVG(u.circulation_hours) AS avg_h, COUNT(*) AS cnt
           FROM write_offs w JOIN units u ON u.id = w.unit_id
           WHERE w.part_id = %s AND w.reason = 'repair' AND w.unit_id IS NOT NULL""",
        [part_id],
    )
    if not row or not row["cnt"]:
        return None
    return round(float(row["avg_h"]), 2)
