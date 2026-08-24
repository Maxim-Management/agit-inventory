from flask import Blueprint, render_template, request

from . import db
from .auth import login_required
from .analytics import repair_usage_by_period, ops_report

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
