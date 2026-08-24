import csv
import io

from flask import Blueprint, render_template, request, Response

from . import db
from .auth import login_required
from .analytics import (
    repair_usage_by_period, ops_report, stock_report_rows, tool_hours_report_rows,
    component_hours_report_rows, revenue_report_rows,
)
from .jobs import list_jobs, JOB_TYPE_LABELS
from .customers import WORK_RATE_UNIT_LABELS

bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@bp.route("/")
@login_required
def index():
    granularity = request.args.get("granularity", "month")
    months_back = int(request.args.get("months_back", 12))
    part_id = request.args.get("part_id") or None
    tool_size = request.args.get("tool_size") or None

    parts = db.query_all("SELECT id, part_name, part_number FROM parts ORDER BY part_name")
    tool_sizes = [r["tool_size"] for r in db.query_all(
        "SELECT DISTINCT tool_size FROM parts WHERE tool_size != '' ORDER BY tool_size")]

    data = repair_usage_by_period(granularity=granularity, months_back=months_back,
                                   part_id=part_id, tool_size=tool_size)

    return render_template(
        "analytics/index.html", data=data, parts=parts, tool_sizes=tool_sizes,
        granularity=granularity, months_back=months_back, part_id=part_id, tool_size=tool_size,
    )


@bp.route("/report")
@login_required
def report():
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    data = ops_report(date_from=date_from, date_to=date_to)
    return render_template("analytics/report.html", data=data, date_from=date_from, date_to=date_to)


@bp.route("/report/export.csv")
@login_required
def export_report_csv():
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    include_stock = request.args.get("include_stock") == "1"
    include_tool_hours = request.args.get("include_tool_hours") == "1"
    include_component_hours = request.args.get("include_component_hours") == "1"
    include_revenue = request.args.get("include_revenue") == "1"
    include_costs = request.args.get("include_costs") == "1"

    period_suffix = ""
    if date_from or date_to:
        period_suffix = f" ({date_from or '...'} — {date_to or '...'})"

    buf = io.StringIO()
    writer = csv.writer(buf)
    wrote_any = False

    if include_stock:
        writer.writerow(["Остатки на складе (на текущий момент)"])
        writer.writerow(["Типоразмер", "Наименование", "Номенкл. №", "Остаток", "Стоимость остатка, RUB", "Курс (средневзв. по остатку)"])
        for row in stock_report_rows():
            writer.writerow([row["tool_size"], row["part_name"], row["part_number"], row["current_stock"],
                              row["stock_value_rub"], row["avg_exchange_rate"] if row["avg_exchange_rate"] is not None else ""])
        writer.writerow([])
        wrote_any = True

    if include_tool_hours:
        writer.writerow(["Наработка по инструментам (на текущий момент)"])
        writer.writerow(["Серийный №", "Типоразмер", "Наработка, ч"])
        for row in tool_hours_report_rows():
            writer.writerow([row["serial_number"], row["tool_size"], row["hours"]])
        writer.writerow([])
        wrote_any = True

    if include_component_hours:
        writer.writerow(["Наработка по компонентам (на текущий момент)"])
        writer.writerow(["Серийный №", "Деталь", "Номенкл. №", "Наработка, ч"])
        for row in component_hours_report_rows():
            writer.writerow([row["serial_number"], row["part_name"], row["part_number"], row["hours"]])
        writer.writerow([])
        wrote_any = True

    if include_revenue:
        writer.writerow([f"Выручка по инструментам{period_suffix}"])
        writer.writerow(["Дата", "Инструмент", "Заказчик", "Скв. №", "Работа", "Ед.", "Дежурство, сут", "Сумма, RUB"])
        for r in revenue_report_rows(date_from, date_to):
            writer.writerow([
                r["revenue_date"], r["tool_serial"], r["customer_name"] or "", r["well_number"] or "",
                r["work_qty"] if r["work_qty"] is not None else "",
                WORK_RATE_UNIT_LABELS.get(r["work_unit"], "") if r["work_qty"] is not None else "",
                r["standby_days"] if r["standby_days"] is not None else "", r["amount"],
            ])
        writer.writerow([])
        wrote_any = True

    if include_costs:
        writer.writerow([f"Затраты по работам{period_suffix}"])
        writer.writerow(["Дата", "Тип", "Инструмент", "Название", "Итого, RUB"])
        for j in list_jobs(date_from=date_from, date_to=date_to):
            writer.writerow([j["job_date"], JOB_TYPE_LABELS.get(j["job_type"], j["job_type"]),
                              j["tool_serial"] or "", j["title"], j["total_cost"]])
        wrote_any = True

    if not wrote_any:
        writer.writerow(["Не выбрано ни одного параметра для выгрузки."])

    return Response(
        buf.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ops_report.csv"},
    )
