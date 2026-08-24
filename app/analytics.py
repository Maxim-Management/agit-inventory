"""Аналитика расхода компонентов по периодам и прогноз заказа на 3 месяца."""
import math
from collections import defaultdict
from datetime import date

from . import db
from .stock import stock_map

REASON_LABELS = {
    "repair": "Ремонт",
    "defect": "Брак",
    "damage": "Повреждение",
    "other": "Другое",
}


def _period_key(d: date, granularity: str) -> str:
    if granularity == "quarter":
        q = (d.month - 1) // 3 + 1
        return f"{d.year}-Q{q}"
    return f"{d.year}-{d.month:02d}"


def _parse_date(value):
    if isinstance(value, date):
        return value
    if value is None:
        return None
    s = str(value)[:10]
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def repair_usage_by_period(granularity="month", months_back=12, part_id=None, tool_size=None):
    """Возвращает данные для графика/таблицы: расход (списания) по деталям
    и периодам, с разбивкой по причине списания."""
    rows = db.query_all(
        """
        SELECT w.id, w.write_off_date, w.reason, w.quantity, w.part_id,
               p.part_name, p.part_number, p.tool_size
        FROM write_offs w
        JOIN parts p ON p.id = w.part_id
        ORDER BY w.write_off_date
        """
    )

    filtered = []
    for r in rows:
        d = _parse_date(r["write_off_date"])
        if d is None:
            continue
        if part_id and str(r["part_id"]) != str(part_id):
            continue
        if tool_size and r["tool_size"] != tool_size:
            continue
        filtered.append((d, r))

    periods = sorted({_period_key(d, granularity) for d, _ in filtered})

    by_period_reason = defaultdict(lambda: defaultdict(float))
    by_part_period = defaultdict(lambda: defaultdict(float))
    part_labels = {}

    for d, r in filtered:
        pk = _period_key(d, granularity)
        qty = float(r["quantity"] or 1)
        by_period_reason[pk][r["reason"]] += qty
        part_key = f'{r["part_name"]} ({r["part_number"]})'
        part_labels[r["part_id"]] = part_key
        by_part_period[part_key][pk] += qty

    reason_series = {reason: [by_period_reason[p].get(reason, 0) for p in periods]
                      for reason in REASON_LABELS}

    part_table = []
    for part_key, period_counts in sorted(by_part_period.items()):
        total = sum(period_counts.values())
        part_table.append({
            "part": part_key,
            "counts": [period_counts.get(p, 0) for p in periods],
            "total": total,
        })
    part_table.sort(key=lambda x: -x["total"])

    return {
        "periods": periods,
        "reason_series": reason_series,
        "reason_labels": REASON_LABELS,
        "part_table": part_table,
        "total_writeoffs": len(filtered),
    }


def forecast_orders(lookback_months=6, horizon_months=3):
    """Для каждой детали: средний месячный расход (по историческим списаниям
    типа ремонт/брак/повреждение) * горизонт (3 мес.) минус текущий остаток,
    с учётом минимального неснижаемого остатка (min_stock_qty)."""
    parts = db.query_all("SELECT * FROM parts ORDER BY part_name")

    cutoff = _months_ago(lookback_months)

    writeoff_sums = db.query_all(
        """
        SELECT part_id, COALESCE(SUM(quantity),0) AS qty
        FROM write_offs
        WHERE write_off_date >= %s
        GROUP BY part_id
        """,
        [cutoff.isoformat()],
    )
    consumption_by_part = {row["part_id"]: float(row["qty"]) for row in writeoff_sums}

    stock_by_part = stock_map()

    results = []
    for part in parts:
        pid = part["id"]
        consumed = consumption_by_part.get(pid, 0)
        avg_monthly = consumed / lookback_months if lookback_months else 0
        projected_need = avg_monthly * horizon_months
        current_stock = stock_by_part.get(pid, 0)
        min_stock = part["min_stock_qty"] or 0
        recommended = max(0, math.ceil(projected_need + min_stock - current_stock))
        results.append({
            "part": part,
            "avg_monthly_consumption": round(avg_monthly, 2),
            "projected_need_3mo": round(projected_need, 2),
            "current_stock": current_stock,
            "min_stock_qty": min_stock,
            "recommended_order_qty": recommended,
            "priority": "высокий" if recommended > 0 and current_stock <= min_stock else
                        ("средний" if recommended > 0 else "низкий"),
        })

    results.sort(key=lambda r: (-r["recommended_order_qty"], r["part"]["part_name"]))
    return results


def ops_report(date_from=None, date_to=None):
    """Сводный отчёт для «Аналитики»: остаток комплектующих на складе,
    средняя наработка на инструмент, средняя наработка на компонент, общая
    выручка на все инструменты, общие затраты (по работам/ремонтам).

    Остаток склада и средняя наработка — всегда на текущий момент (снимок,
    без фильтра по датам): наработка и остаток — это накопленное состояние,
    а не событие с датой, которое имело бы смысл резать по периоду.
    Выручка и затраты, наоборот, считаются за выбранный период (date_from/
    date_to, оба включительно) — как в аналогичном отчёте по работам в
    разделе «Сервис» (app/routes_jobs.py: report())."""
    from .stock import total_stock_value
    from .jobs import list_jobs

    stock_value_rub = total_stock_value()

    tools_count_row = db.query_one("SELECT COUNT(*) AS c FROM tools")
    tools_count = tools_count_row["c"] if tools_count_row else 0
    tool_hours_rows = db.query_all(
        "SELECT tool_id, COALESCE(SUM(hours_added),0) AS s FROM tool_usage_logs GROUP BY tool_id"
    )
    total_tool_hours = sum(float(r["s"] or 0) for r in tool_hours_rows)
    avg_tool_hours = round(total_tool_hours / tools_count, 2) if tools_count else 0.0

    component_row = db.query_one("SELECT AVG(circulation_hours) AS avg_h, COUNT(*) AS c FROM units")
    components_count = component_row["c"] if component_row else 0
    avg_component_hours = round(float(component_row["avg_h"]), 2) if components_count and component_row["avg_h"] is not None else 0.0

    revenue_sql = "SELECT COALESCE(SUM(amount),0) AS s FROM tool_revenue WHERE 1=1"
    params = []
    if date_from:
        revenue_sql += " AND revenue_date >= %s"
        params.append(date_from)
    if date_to:
        revenue_sql += " AND revenue_date <= %s"
        params.append(date_to)
    total_revenue = round(float(db.query_one(revenue_sql, params)["s"] or 0), 2)

    jobs = list_jobs(date_from=date_from, date_to=date_to)
    total_costs = round(sum(j["total_cost"] for j in jobs), 2)

    return {
        "stock_value_rub": round(stock_value_rub, 2),
        "tools_count": tools_count,
        "avg_tool_hours": avg_tool_hours,
        "components_count": components_count,
        "avg_component_hours": avg_component_hours,
        "total_revenue": total_revenue,
        "total_costs": total_costs,
        "net_result": round(total_revenue - total_costs, 2),
        "jobs_count": len(jobs),
    }


def stock_report_rows():
    """Детальная строка по КАЖДОЙ детали справочника — для выгрузки
    «Остатки на складе» в сводном отчёте (агрегат — total_stock_value() —
    показывается на экране, а для выгрузки нужна расшифровка по деталям)."""
    from .stock import stock_map, part_stock_value

    stock = stock_map()
    parts = db.query_all("SELECT id, tool_size, part_name, part_number FROM parts ORDER BY part_name")
    rows = []
    for p in parts:
        sv = part_stock_value(p["id"])
        rows.append({
            "tool_size": p["tool_size"], "part_name": p["part_name"], "part_number": p["part_number"],
            "current_stock": stock.get(p["id"], 0),
            "stock_value_rub": sv["stock_value_rub"],
            "avg_exchange_rate": sv["avg_exchange_rate"],
        })
    return rows


def tool_hours_report_rows():
    """Наработка по КАЖДОМУ инструменту — для выгрузки в сводном отчёте."""
    rows = db.query_all(
        """SELECT t.serial_number, t.tool_size, COALESCE(SUM(l.hours_added), 0) AS hours
           FROM tools t LEFT JOIN tool_usage_logs l ON l.tool_id = t.id
           GROUP BY t.id, t.serial_number, t.tool_size
           ORDER BY t.serial_number"""
    )
    return [{"serial_number": r["serial_number"], "tool_size": r["tool_size"], "hours": float(r["hours"] or 0)}
            for r in rows]


def component_hours_report_rows():
    """Наработка по КАЖДОМУ серийному компоненту — для выгрузки в сводном отчёте."""
    rows = db.query_all(
        """SELECT u.serial_number, p.part_name, p.part_number, u.circulation_hours
           FROM units u JOIN parts p ON p.id = u.part_id
           ORDER BY p.part_name, u.serial_number"""
    )
    return [{"serial_number": r["serial_number"], "part_name": r["part_name"], "part_number": r["part_number"],
              "hours": float(r["circulation_hours"] or 0)} for r in rows]


def revenue_report_rows(date_from=None, date_to=None):
    """Строки выручки (по инструментам) за период — для выгрузки в сводном отчёте."""
    sql = """SELECT tr.revenue_date, t.serial_number AS tool_serial, c.name AS customer_name,
                     tr.well_number, tr.work_qty, tr.work_unit, tr.standby_days, tr.amount
             FROM tool_revenue tr
             JOIN tools t ON t.id = tr.tool_id
             LEFT JOIN customers c ON c.id = tr.customer_id
             WHERE 1=1"""
    params = []
    if date_from:
        sql += " AND tr.revenue_date >= %s"
        params.append(date_from)
    if date_to:
        sql += " AND tr.revenue_date <= %s"
        params.append(date_to)
    sql += " ORDER BY tr.revenue_date, tr.id"
    return db.query_all(sql, params)


def _months_ago(n):
    today = date.today()
    year = today.year
    month = today.month - n
    while month <= 0:
        month += 12
        year -= 1
    day = min(today.day, 28)
    return date(year, month, day)
