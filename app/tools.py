"""Реестр инструментов (буровых компоновок) с собственными серийными
номерами. Инструмент — это физическая единица, на которую устанавливаются
серийные компоненты (units): ротор, статор и т.п. Для инструмента отдельно
ведётся:
  - наработка (tool_usage_logs) — при внесении записи она автоматически
    зеркалируется в usage_logs и circulation_hours КАЖДОГО компонента,
    установленного на инструменте на момент записи (units.installed_on_tool_id);
  - выручка (tool_revenue);
  - стоимость ремонтных/сборочных работ (service_jobs.tool_id);
  - начисленная амортизация (см. tool_depreciation() ниже) — 1/18
    себестоимости инструмента (tools.cost_rub) за каждый полный месяц с
    даты ввода в эксплуатацию (commissioned_date), не более 18 месяцев
    (то есть не более полной себестоимости).
  Рентабельность = выручка − (начисленная амортизация + стоимость ремонтов).
"""
from datetime import date

from . import db
from .jobs import job_totals

STATUS_LABELS = {"active": "В работе", "in_repair": "В ремонте", "retired": "Списан"}

# Срок полезного использования для расчёта амортизации, мес. — 1/18
# себестоимости инструмента начисляется за каждый полный месяц эксплуатации.
DEPRECIATION_MONTHS = 18


def _as_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def months_elapsed(start_date, as_of=None):
    """Число ПОЛНЫХ календарных месяцев между start_date и as_of (по
    умолчанию — сегодня). Месяц засчитывается только по достижении того же
    числа месяца, что и в start_date (т.е. "с даты по дату"), не раньше.
    Отрицательный результат (as_of раньше start_date) отдаётся как 0."""
    start = _as_date(start_date)
    if start is None:
        return 0
    today = _as_date(as_of) if as_of is not None else date.today()
    if today < start:
        return 0
    months = (today.year - start.year) * 12 + (today.month - start.month)
    if today.day < start.day:
        months -= 1
    return max(0, months)


def tool_depreciation(tool, as_of=None):
    """Начисленная амортизация инструмента на дату as_of (по умолчанию —
    сегодня): 1/18 себестоимости (tools.cost_rub) за каждый полный месяц с
    даты ввода в эксплуатацию (tools.commissioned_date), не более
    DEPRECIATION_MONTHS месяцев — то есть не более полной себестоимости.
    Без указанной себестоимости или даты ввода в эксплуатацию амортизация
    считается неопределённой (0, fully_depreciated=False)."""
    cost = float(tool.get("cost_rub") or 0)
    commissioned = tool.get("commissioned_date")
    if not cost or not commissioned:
        return {
            "monthly_rub": 0.0, "accrued_rub": 0.0,
            "months_elapsed": 0, "months_total": DEPRECIATION_MONTHS,
            "fully_depreciated": False, "has_data": False,
        }
    monthly = cost / DEPRECIATION_MONTHS
    elapsed = min(months_elapsed(commissioned, as_of), DEPRECIATION_MONTHS)
    accrued = round(monthly * elapsed, 2)
    return {
        "monthly_rub": round(monthly, 2), "accrued_rub": min(accrued, round(cost, 2)),
        "months_elapsed": elapsed, "months_total": DEPRECIATION_MONTHS,
        "fully_depreciated": elapsed >= DEPRECIATION_MONTHS, "has_data": True,
    }

# Наименование инструмента считается автоматически по типоразмеру (в
# типоразмере может быть указано по-разному — с кавычками/без, с пробелом/
# без — поэтому сравнение идёт по вхождению цифр размера в нормализованную
# строку, а не по точному совпадению).
#
# ВАЖНО: для размера 6 3/4" пользователь указал то же имя, что и для 4 3/4"
# (видимо, опечатка при постановке задачи) — здесь применена схема по
# аналогии с двумя другими размерами (АГИТ-<размер в десятичной дроби>-IM).
# Если для 6 3/4" должно быть какое-то другое имя — скажите, поправим.
_TOOL_NAME_RULES = [
    ("4 3/4", "AGIT-4.75-IM"),
    ("6 3/4", "AGIT-6.75-IM"),
    ("8", "AGIT-8-IM"),
]


def tool_display_name(tool_size):
    """Наименование инструмента по типоразмеру (см. _TOOL_NAME_RULES выше).
    Возвращает пустую строку, если типоразмер не распознан ни под одно
    правило (тогда в интерфейсе просто ничего не показываем)."""
    size = (tool_size or "").strip()
    if not size:
        return ""
    for needle, name in _TOOL_NAME_RULES:
        if needle in size:
            return name
    return ""


def create_tool(serial_number, tool_size, status, commissioned_date, cost_rub, location, note, created_by):
    return db.execute_returning_id(
        """INSERT INTO tools (serial_number, tool_size, status, commissioned_date, cost_rub, location, note, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        [serial_number, tool_size, status or "active", commissioned_date or None, cost_rub,
         location or "", note or "", created_by],
    )


def get_tool(tool_id):
    return db.query_one("SELECT * FROM tools WHERE id = %s", [tool_id])


def tool_jobs_cost(tool_id):
    jobs = db.query_all("SELECT * FROM service_jobs WHERE tool_id = %s", [tool_id])
    total = 0.0
    for j in jobs:
        total += job_totals(j)["total_cost"]
    return round(total, 2)


def tool_totals(tool_id):
    hours_row = db.query_one(
        "SELECT COALESCE(SUM(hours_added),0) AS s FROM tool_usage_logs WHERE tool_id = %s", [tool_id]
    )
    cumulative_hours = float(hours_row["s"] or 0)

    revenue_row = db.query_one(
        "SELECT COALESCE(SUM(amount),0) AS s FROM tool_revenue WHERE tool_id = %s", [tool_id]
    )
    cumulative_revenue = float(revenue_row["s"] or 0)

    jobs_cost = tool_jobs_cost(tool_id)

    installed_row = db.query_one(
        "SELECT COUNT(*) AS c FROM units WHERE installed_on_tool_id = %s AND status = 'installed'", [tool_id]
    )
    installed_count = installed_row["c"] or 0

    tool = get_tool(tool_id) or {}
    depreciation = tool_depreciation(tool)

    return {
        "cumulative_hours": cumulative_hours,
        "cumulative_revenue": round(cumulative_revenue, 2),
        "jobs_cost": jobs_cost,
        "depreciation": depreciation,
        # Рентабельность = выручка − (начисленная амортизация + стоимость ремонтов).
        "profitability": round(cumulative_revenue - (depreciation["accrued_rub"] + jobs_cost), 2),
        "installed_count": installed_count,
    }


def list_tools(status=None, q=None):
    sql = "SELECT * FROM tools WHERE 1=1"
    params = []
    if status:
        sql += " AND status = %s"
        params.append(status)
    if q:
        sql += " AND (serial_number LIKE %s OR tool_size LIKE %s)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY serial_number"
    tools = db.query_all(sql, params)
    for t in tools:
        t.update(tool_totals(t["id"]))
        t["tool_name"] = tool_display_name(t["tool_size"])
    return tools


def installed_units(tool_id):
    return db.query_all(
        """SELECT u.*, p.part_name, p.part_number, p.category
           FROM units u JOIN parts p ON p.id = u.part_id
           WHERE u.installed_on_tool_id = %s AND u.status = 'installed'
           ORDER BY p.category, p.part_name""",
        [tool_id],
    )


def install_unit(unit_id, tool_id):
    tool = get_tool(tool_id)
    if not tool:
        raise ValueError("Инструмент не найден")
    db.execute(
        "UPDATE units SET status = 'installed', installed_on_tool_id = %s, installed_on = %s WHERE id = %s",
        [tool_id, tool["serial_number"], unit_id],
    )


def remove_unit(unit_id):
    db.execute(
        "UPDATE units SET status = 'in_stock', installed_on_tool_id = NULL, installed_on = '' WHERE id = %s",
        [unit_id],
    )


def log_tool_usage(tool_id, log_date, hours_added, note, created_by):
    """Вносит наработку инструмента и пропагирует её на все установленные
    сейчас на нём серийные компоненты (создаёт им зеркальные usage_logs,
    связанные с этой записью через source_tool_usage_log_id, и увеличивает
    circulation_hours). Возвращает {"log_id", "affected"} — id созданной
    записи наработки инструмента (используется, например, чтобы связать её
    с записью выручки — см. log_tool_revenue ниже) и число затронутых
    компонентов."""
    tool = get_tool(tool_id)
    if not tool:
        raise ValueError("Инструмент не найден")
    log_id = db.execute_returning_id(
        "INSERT INTO tool_usage_logs (tool_id, log_date, hours_added, note, created_by) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        [tool_id, log_date, hours_added, note or "", created_by],
    )
    units = installed_units(tool_id)
    for u in units:
        db.execute(
            """INSERT INTO usage_logs (unit_id, log_date, hours_added, service_count_added, tool_assembly,
                                        note, source_tool_usage_log_id, created_by)
               VALUES (%s,%s,%s,0,%s,%s,%s,%s)""",
            [u["id"], log_date, hours_added, tool["serial_number"],
             note or f"Наработка инструмента {tool['serial_number']}", log_id, created_by],
        )
        db.execute("UPDATE units SET circulation_hours = circulation_hours + %s WHERE id = %s", [hours_added, u["id"]])
    return {"log_id": log_id, "affected": len(units)}


def edit_tool_usage(tool_id, log_id, log_date, hours_added, note):
    """Редактирует запись наработки инструмента (только администратор) и
    пересчитывает зеркальные записи/наработку затронутых компонентов на
    разницу между старым и новым значением часов."""
    old = db.query_one("SELECT * FROM tool_usage_logs WHERE id = %s AND tool_id = %s", [log_id, tool_id])
    if not old:
        raise ValueError("Запись наработки не найдена")
    delta = float(hours_added) - float(old["hours_added"] or 0)
    db.execute(
        "UPDATE tool_usage_logs SET log_date=%s, hours_added=%s, note=%s WHERE id=%s",
        [log_date, hours_added, note or "", log_id],
    )
    mirrored = db.query_all("SELECT * FROM usage_logs WHERE source_tool_usage_log_id = %s", [log_id])
    for m in mirrored:
        db.execute(
            "UPDATE usage_logs SET log_date=%s, hours_added=%s WHERE id=%s",
            [log_date, hours_added, m["id"]],
        )
        if delta:
            db.execute(
                "UPDATE units SET circulation_hours = circulation_hours + %s WHERE id = %s",
                [delta, m["unit_id"]],
            )


def delete_tool_usage(tool_id, log_id):
    """Удаляет запись наработки инструмента (только администратор) и
    откатывает добавленные ею часы у всех затронутых компонентов, прежде
    чем зеркальные записи будут удалены каскадно вместе с ней."""
    old = db.query_one("SELECT * FROM tool_usage_logs WHERE id = %s AND tool_id = %s", [log_id, tool_id])
    if not old:
        raise ValueError("Запись наработки не найдена")
    mirrored = db.query_all("SELECT * FROM usage_logs WHERE source_tool_usage_log_id = %s", [log_id])
    for m in mirrored:
        db.execute(
            "UPDATE units SET circulation_hours = circulation_hours - %s WHERE id = %s",
            [m["hours_added"], m["unit_id"]],
        )
    # ON DELETE CASCADE на usage_logs.source_tool_usage_log_id удалит
    # зеркальные записи автоматически вместе с исходной.
    db.execute("DELETE FROM tool_usage_logs WHERE id = %s", [log_id])


def log_tool_revenue(tool_id, revenue_date, note, created_by, amount=None, currency="RUB",
                      customer_id=None, well_number="", work_hours=0, standby_days=0):
    """Вносит запись о выручке. Два режима:
      - customer_id не задан (прежний способ, вручную) — сумма (amount)
        вводится оператором напрямую.
      - customer_id задан — сумма считается автоматически по ставкам
        заказчика (work_hours * ставка часа + standby_days * ставка суток),
        ставки "замораживаются" на записи (work_rate_rub_per_hour/
        standby_rate_rub_per_day), а часы работы (work_hours), если больше
        нуля, переносятся в наработку инструмента через log_tool_usage() —
        id созданной записи наработки сохраняется в usage_log_id, чтобы при
        удалении этой записи выручки можно было откатить и её.
    Возвращает фактически сохранённую сумму (amount)."""
    from . import customers as customers_mod

    work_rate = None
    standby_rate = None
    usage_log_id = None
    work_hours = float(work_hours or 0)
    standby_days = float(standby_days or 0)

    if customer_id:
        customer = customers_mod.get_customer(customer_id)
        if not customer:
            raise ValueError("Заказчик не найден")
        work_rate = float(customer["work_rate_rub_per_hour"] or 0)
        standby_rate = float(customer["standby_rate_rub_per_day"] or 0)
        amount = round(work_hours * work_rate + standby_days * standby_rate, 2)
        if work_hours > 0:
            usage_note = note or (f"Наработка по выручке, скв. {well_number}" if well_number else "Наработка по выручке")
            usage_log_id = log_tool_usage(tool_id, revenue_date, work_hours, usage_note, created_by)["log_id"]
    else:
        amount = float(amount or 0)

    db.execute(
        """INSERT INTO tool_revenue (tool_id, revenue_date, amount, currency, note, created_by,
                                       customer_id, well_number, work_hours, standby_days,
                                       work_rate_rub_per_hour, standby_rate_rub_per_day, usage_log_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [tool_id, revenue_date, amount, currency or "RUB", note or "", created_by,
         customer_id or None, well_number or "", work_hours if customer_id else None,
         standby_days if customer_id else None, work_rate, standby_rate, usage_log_id],
    )
    return amount


def edit_tool_revenue(tool_id, revenue_id, revenue_date, amount, note):
    """Правка вручную внесённой записи выручки (дата/сумма/примечание) —
    доступна только для записей БЕЗ привязки к заказчику; записи, созданные
    через выбор заказчика, правятся только удалением и повторным вводом
    (иначе сумма разошлась бы с уже перенесённой наработкой)."""
    db.execute(
        "UPDATE tool_revenue SET revenue_date=%s, amount=%s, note=%s WHERE id=%s AND tool_id=%s AND customer_id IS NULL",
        [revenue_date, amount, note or "", revenue_id, tool_id],
    )


def delete_tool_revenue(tool_id, revenue_id):
    """Удаляет запись о выручке. Если она была создана через выбор заказчика
    и перенесла часы в наработку (usage_log_id задан) — сначала откатывает и
    удаляет эту связанную запись наработки (и её зеркальные записи у
    установленных компонентов), как при обычном удалении наработки."""
    row = db.query_one("SELECT * FROM tool_revenue WHERE id = %s AND tool_id = %s", [revenue_id, tool_id])
    if not row:
        return
    if row.get("usage_log_id"):
        try:
            delete_tool_usage(tool_id, row["usage_log_id"])
        except ValueError:
            pass
    db.execute("DELETE FROM tool_revenue WHERE id = %s AND tool_id = %s", [revenue_id, tool_id])


def tool_usage_history(tool_id):
    return db.query_all(
        "SELECT * FROM tool_usage_logs WHERE tool_id = %s ORDER BY log_date, id", [tool_id]
    )


def tool_revenue_history(tool_id):
    return db.query_all(
        """SELECT tr.*, c.name AS customer_name FROM tool_revenue tr
           LEFT JOIN customers c ON c.id = tr.customer_id
           WHERE tr.tool_id = %s ORDER BY tr.revenue_date DESC, tr.id DESC""",
        [tool_id],
    )


def tool_jobs(tool_id):
    jobs = db.query_all(
        "SELECT * FROM service_jobs WHERE tool_id = %s ORDER BY job_date DESC, id DESC", [tool_id]
    )
    for j in jobs:
        j.update(job_totals(j))
    return jobs
