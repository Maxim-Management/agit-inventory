"""Ремонтные/сборочные работы: группировка списанных компонентов и прочих
затрат (сервисный центр, персонал, другое) для отчёта по стоимости работы."""
from . import db
from .costing import write_off_unit_cost_rub

JOB_TYPE_LABELS = {"repair": "Ремонт", "assembly": "Сборка", "other": "Другое"}

# Общие поля партии/детали для расчёта стоимости списания по факту той
# партии, из которой оно произошло (write_offs.receipt_id) — см.
# app/costing.py: write_off_unit_cost_rub(). LEFT JOIN на receipts, потому
# что у части списаний партия может быть не привязана (см. докстринг
# write_off_unit_cost_rub) — тогда используется запасной вариант,
# "текущие" (последнего поступления) значения самой детали.
_WRITE_OFF_COST_JOIN_SQL = """
    JOIN parts p ON p.id = w.part_id
    LEFT JOIN receipts r ON r.id = w.receipt_id
"""
_WRITE_OFF_COST_FIELDS_SQL = """
    p.customs_duty_percent,
    p.standard_cost_cny AS part_standard_cost_cny, p.exchange_rate AS part_exchange_rate,
    p.unit_transfer_price_rub AS part_unit_transfer_price_rub,
    r.total_cost_cny AS receipt_total_cost_cny, r.quantity AS receipt_quantity,
    r.exchange_rate AS receipt_exchange_rate, r.transfer_price_rub AS receipt_transfer_price_rub
"""


def job_parts_cost(job_id):
    """Стоимость списанных на работу компонентов — по расчётной стоимости
    за единицу ТОЙ ПАРТИИ, из которой компонент реально был списан
    (себестоимость × курс юаня × (1 + пошлина) + трансфер прайс, см.
    app/costing.py: write_off_unit_cost_rub), а не по одному только
    трансфер прайсу и не по "текущим" (последнего поступления) значениям
    карточки детали, которые могли устареть или отличаться от факта
    конкретной партии."""
    rows = db.query_all(
        f"""SELECT w.quantity, {_WRITE_OFF_COST_FIELDS_SQL}
           FROM write_offs w {_WRITE_OFF_COST_JOIN_SQL}
           WHERE w.job_id = %s""",
        [job_id],
    )
    total = 0.0
    priced = 0
    unpriced = 0
    for r in rows:
        qty = float(r["quantity"] or 0)
        # Приценено, если есть хотя бы один из компонентов формулы (из
        # партии или из "текущих" данных детали) — иначе (всё пусто)
        # считаем строку неоценённой, как раньше.
        if r["receipt_total_cost_cny"] is None and r["part_standard_cost_cny"] is None \
                and r["receipt_transfer_price_rub"] is None and r["part_unit_transfer_price_rub"] is None:
            unpriced += 1
            continue
        total += qty * write_off_unit_cost_rub(r)
        priced += 1
    return {"parts_cost": round(total, 2), "priced_lines": priced, "unpriced_lines": unpriced}


def job_unit_repairs(job_id):
    """Ремонты серийных компонентов, отнесённые на эту работу (см.
    app/routes_units.py: repair()) — при выборе работы стоимость ремонта
    компонента ложится в стоимость этой работы, а сам компонент
    устанавливается на инструмент работы."""
    return db.query_all(
        """SELECT ur.*, u.serial_number, p.part_name, p.part_number
           FROM unit_repairs ur
           JOIN units u ON u.id = ur.unit_id
           JOIN parts p ON p.id = u.part_id
           WHERE ur.job_id = %s
           ORDER BY ur.repair_date DESC, ur.id DESC""",
        [job_id],
    )


def job_unit_repairs_cost(job_id):
    row = db.query_one("SELECT COALESCE(SUM(cost_rub),0) AS s FROM unit_repairs WHERE job_id = %s", [job_id])
    return round(float(row["s"] or 0), 2)


def job_totals(job):
    parts_cost = job_parts_cost(job["id"])["parts_cost"]
    service = float(job["service_center_cost"] or 0)
    labor = float(job["labor_cost"] or 0)
    other = float(job["other_cost"] or 0)
    component_repairs_cost = job_unit_repairs_cost(job["id"])
    return {
        "parts_cost": parts_cost,
        "service_center_cost": service,
        "labor_cost": labor,
        "other_cost": other,
        "component_repairs_cost": component_repairs_cost,
        "total_cost": round(parts_cost + service + labor + other + component_repairs_cost, 2),
    }


def delete_job(job_id):
    """Удаляет работу целиком: списанные на неё компоненты возвращаются на
    склад (записи списания удаляются, партии — пополняются). Записи о
    ремонте серийных компонентов (unit_repairs), отнесённые на эту работу,
    НЕ удаляются — история ремонта конкретного компонента ценна сама по
    себе, — а просто отвязываются от работы (job_id -> NULL), переставая
    учитываться в стоимости удаляемой работы. Возвращает число возвращённых
    на склад списаний."""
    restored = 0
    write_offs = db.query_all("SELECT * FROM write_offs WHERE job_id = %s", [job_id])
    for w in write_offs:
        if w["unit_id"]:
            db.execute(
                "UPDATE units SET status = 'in_stock', installed_on_tool_id = NULL, installed_on = '' WHERE id = %s",
                [w["unit_id"]],
            )
        if w["receipt_id"]:
            db.execute(
                "UPDATE receipts SET remaining_quantity = remaining_quantity + %s WHERE id = %s",
                [w["quantity"], w["receipt_id"]],
            )
        db.execute("DELETE FROM write_offs WHERE id = %s", [w["id"]])
        restored += 1
    db.execute("UPDATE unit_repairs SET job_id = NULL WHERE job_id = %s", [job_id])
    db.execute("DELETE FROM service_jobs WHERE id = %s", [job_id])
    return restored


def list_jobs(job_type=None, date_from=None, date_to=None, tool_id=None):
    sql = """SELECT sj.*, t.serial_number AS tool_serial
             FROM service_jobs sj LEFT JOIN tools t ON t.id = sj.tool_id
             WHERE 1=1"""
    params = []
    if job_type:
        sql += " AND sj.job_type = %s"
        params.append(job_type)
    if date_from:
        sql += " AND sj.job_date >= %s"
        params.append(date_from)
    if date_to:
        sql += " AND sj.job_date <= %s"
        params.append(date_to)
    if tool_id:
        sql += " AND sj.tool_id = %s"
        params.append(tool_id)
    sql += " ORDER BY sj.job_date DESC, sj.id DESC"
    jobs = db.query_all(sql, params)
    for j in jobs:
        j.update(job_totals(j))
    return jobs


def job_write_offs(job_id):
    rows = db.query_all(
        f"""SELECT w.*, p.part_name, p.part_number, u.serial_number, {_WRITE_OFF_COST_FIELDS_SQL}
           FROM write_offs w {_WRITE_OFF_COST_JOIN_SQL}
           LEFT JOIN units u ON u.id = w.unit_id
           WHERE w.job_id = %s
           ORDER BY w.write_off_date DESC, w.id DESC""",
        [job_id],
    )
    for r in rows:
        # write_off_unit_cost_rub() уже возвращает float; r["quantity"] на
        # Postgres приходит как decimal.Decimal — умножать его на float
        # напрямую нельзя (TypeError), поэтому приводим и считаем итог по
        # строке здесь же, чтобы в шаблоне не оставалось "сырой" арифметики
        # с Decimal.
        r["unit_cost_rub"] = write_off_unit_cost_rub(r)
        r["line_cost_rub"] = r["unit_cost_rub"] * float(r["quantity"] or 0)
    return rows
