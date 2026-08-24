"""Ремонтные/сборочные работы: группировка списанных компонентов и прочих
затрат (сервисный центр, персонал, другое) для отчёта по стоимости работы."""
from . import db
from .costing import part_unit_cost_rub

JOB_TYPE_LABELS = {"repair": "Ремонт", "assembly": "Сборка", "other": "Другое"}


def job_parts_cost(job_id):
    """Стоимость списанных на работу компонентов — по расчётной стоимости
    за единицу детали (себестоимость × курс юаня × (1 + пошлина) + трансфер
    прайс, см. app/costing.py), а не по одному только трансфер прайсу."""
    rows = db.query_all(
        """SELECT w.quantity, p.standard_cost_cny, p.exchange_rate, p.customs_duty_percent, p.unit_transfer_price_rub
           FROM write_offs w JOIN parts p ON p.id = w.part_id
           WHERE w.job_id = %s""",
        [job_id],
    )
    total = 0.0
    priced = 0
    unpriced = 0
    for r in rows:
        qty = float(r["quantity"] or 0)
        # Приценено, если есть хотя бы один из компонентов формулы —
        # иначе (все поля пусты) считаем строку неоценённой, как раньше.
        if r["standard_cost_cny"] is None and r["unit_transfer_price_rub"] is None:
            unpriced += 1
            continue
        total += qty * part_unit_cost_rub(r)
        priced += 1
    return {"parts_cost": round(total, 2), "priced_lines": priced, "unpriced_lines": unpriced}


def job_totals(job):
    parts_cost = job_parts_cost(job["id"])["parts_cost"]
    service = float(job["service_center_cost"] or 0)
    labor = float(job["labor_cost"] or 0)
    other = float(job["other_cost"] or 0)
    return {
        "parts_cost": parts_cost,
        "service_center_cost": service,
        "labor_cost": labor,
        "other_cost": other,
        "total_cost": round(parts_cost + service + labor + other, 2),
    }


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
        """SELECT w.*, p.part_name, p.part_number, p.standard_cost_cny, p.exchange_rate,
                  p.customs_duty_percent, p.unit_transfer_price_rub, u.serial_number
           FROM write_offs w
           JOIN parts p ON p.id = w.part_id
           LEFT JOIN units u ON u.id = w.unit_id
           WHERE w.job_id = %s
           ORDER BY w.write_off_date DESC, w.id DESC""",
        [job_id],
    )
    for r in rows:
        # part_unit_cost_rub() уже возвращает float; r["quantity"] на Postgres
        # приходит как decimal.Decimal — умножать его на float напрямую нельзя
        # (TypeError), поэтому приводим и считаем итог по строке здесь же,
        # чтобы в шаблоне не оставалось "сырой" арифметики с Decimal.
        r["unit_cost_rub"] = part_unit_cost_rub(r)
        r["line_cost_rub"] = r["unit_cost_rub"] * float(r["quantity"] or 0)
    return rows
