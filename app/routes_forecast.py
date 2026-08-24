import csv
import io

from flask import Blueprint, render_template, request, Response

from .auth import login_required
from .analytics import forecast_orders

bp = Blueprint("forecast", __name__, url_prefix="/forecast")


@bp.route("/")
@login_required
def index():
    lookback_months = int(request.args.get("lookback_months", 6))
    results = forecast_orders(lookback_months=lookback_months, horizon_months=3)
    total_recommended = sum(r["recommended_order_qty"] for r in results)
    return render_template(
        "forecast/index.html", results=results, lookback_months=lookback_months,
        total_recommended=total_recommended,
    )


@bp.route("/export.csv")
@login_required
def export_csv():
    lookback_months = int(request.args.get("lookback_months", 6))
    results = forecast_orders(lookback_months=lookback_months, horizon_months=3)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Деталь", "Номенклатурный номер", "Типоразмер", "Средний расход/мес",
                      "Прогноз на 3 мес", "Текущий остаток", "Неснижаемый остаток",
                      "Рекомендуемый заказ", "Приоритет"])
    for r in results:
        writer.writerow([
            r["part"]["part_name"], r["part"]["part_number"], r["part"]["tool_size"],
            r["avg_monthly_consumption"], r["projected_need_3mo"], r["current_stock"],
            r["min_stock_qty"], r["recommended_order_qty"], r["priority"],
        ])

    return Response(
        buf.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=forecast_3mo.csv"},
    )
