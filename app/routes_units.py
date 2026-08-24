from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from . import db
from .auth import login_required, roles_required
from .stock import consume_from_batch

bp = Blueprint("units", __name__, url_prefix="/units")


@bp.route("/")
@login_required
def list_units():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    category = request.args.get("category", "").strip()

    sql = """
        SELECT u.*, p.part_name, p.part_number, p.tool_size, p.category
        FROM units u JOIN parts p ON p.id = u.part_id
        WHERE 1=1
    """
    params = []
    if q:
        sql += " AND (u.serial_number LIKE %s OR p.part_name LIKE %s OR p.part_number LIKE %s)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if status:
        sql += " AND u.status = %s"
        params.append(status)
    if category:
        sql += " AND p.category = %s"
        params.append(category)
    sql += " ORDER BY u.created_at DESC LIMIT 500"

    units = db.query_all(sql, params)
    return render_template("units/list.html", units=units, q=q, status=status, category=category)


@bp.route("/new", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def new_unit():
    parts = db.query_all("SELECT * FROM parts ORDER BY part_name")
    if request.method == "POST":
        f = request.form
        serials_raw = f.get("serial_numbers", "").strip()
        serials = [s.strip() for s in serials_raw.splitlines() if s.strip()] or [f.get("serial_number", "").strip()]
        part_id = f["part_id"]
        created = 0
        errors = []
        for serial in serials:
            if not serial:
                continue
            try:
                db.execute(
                    """INSERT INTO units (part_id, serial_number, date_mfg, status, od_mm, id_mm, location, remarks)
                       VALUES (%s,%s,%s,'in_stock',%s,%s,%s,%s)""",
                    [part_id, serial, f.get("date_mfg", ""), f.get("od_mm") or None,
                     f.get("id_mm") or None, f.get("location", ""), f.get("remarks", "")],
                )
                created += 1
            except Exception as e:
                errors.append(f"{serial}: {e}")
        if created:
            flash(f"Добавлено серийных единиц: {created}.", "ok")
        for e in errors:
            flash(f"Ошибка: {e}", "error")
        return redirect(url_for("units.list_units"))
    return render_template("units/new.html", parts=parts)


@bp.route("/<int:unit_id>")
@login_required
def detail(unit_id):
    unit = db.query_one(
        """SELECT u.*, p.part_name, p.part_number, p.tool_size, p.category
           FROM units u JOIN parts p ON p.id = u.part_id WHERE u.id = %s""",
        [unit_id],
    )
    if not unit:
        flash("Компонент не найден.", "error")
        return redirect(url_for("units.list_units"))

    usage_logs = db.query_all(
        "SELECT * FROM usage_logs WHERE unit_id = %s ORDER BY log_date", [unit_id]
    )
    write_offs = db.query_all(
        "SELECT * FROM write_offs WHERE unit_id = %s ORDER BY write_off_date DESC", [unit_id]
    )
    paired_with = None
    if unit.get("paired_with_unit_id"):
        paired_with = db.query_one(
            """SELECT u.*, p.part_name, p.category FROM units u JOIN parts p ON p.id=u.part_id
               WHERE u.id = %s""",
            [unit["paired_with_unit_id"]],
        )

    installed_on_tool = None
    if unit.get("installed_on_tool_id"):
        installed_on_tool = db.query_one("SELECT * FROM tools WHERE id = %s", [unit["installed_on_tool_id"]])

    # накопительная наработка по датам — для графика
    cumulative = []
    total_hours = 0.0
    for log in usage_logs:
        total_hours += float(log["hours_added"] or 0)
        cumulative.append({"date": log["log_date"], "hours": total_hours})

    return render_template(
        "units/detail.html", unit=unit, usage_logs=usage_logs, write_offs=write_offs,
        paired_with=paired_with, cumulative=cumulative, installed_on_tool=installed_on_tool,
    )


@bp.route("/<int:unit_id>/usage", methods=("POST",))
@roles_required("admin", "engineer")
def add_usage(unit_id):
    f = request.form
    hours = float(f.get("hours_added") or 0)
    svc = int(f.get("service_count_added") or 0)
    db.execute(
        """INSERT INTO usage_logs (unit_id, log_date, hours_added, service_count_added, tool_assembly, note, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        [unit_id, f["log_date"], hours, svc, f.get("tool_assembly", ""), f.get("note", ""), g.user["id"]],
    )
    db.execute(
        """UPDATE units SET circulation_hours = circulation_hours + %s,
                             service_count = service_count + %s,
                             installed_on = COALESCE(NULLIF(%s, ''), installed_on)
           WHERE id = %s""",
        [hours, svc, f.get("tool_assembly", ""), unit_id],
    )
    flash("Наработка добавлена.", "ok")
    return redirect(url_for("units.detail", unit_id=unit_id))


@bp.route("/<int:unit_id>/usage/<int:log_id>/edit", methods=("POST",))
@roles_required("admin")
def edit_usage(unit_id, log_id):
    log = db.query_one("SELECT * FROM usage_logs WHERE id = %s AND unit_id = %s", [log_id, unit_id])
    if not log:
        flash("Запись наработки не найдена.", "error")
        return redirect(url_for("units.detail", unit_id=unit_id))
    if log["source_tool_usage_log_id"]:
        flash("Эта запись — зеркало наработки инструмента, редактируйте её на странице инструмента.", "error")
        return redirect(url_for("units.detail", unit_id=unit_id))
    f = request.form
    new_hours = float(f.get("hours_added") or 0)
    new_svc = int(f.get("service_count_added") or 0)
    hours_delta = new_hours - float(log["hours_added"] or 0)
    svc_delta = new_svc - int(log["service_count_added"] or 0)
    db.execute(
        """UPDATE usage_logs SET log_date=%s, hours_added=%s, service_count_added=%s, tool_assembly=%s, note=%s
           WHERE id=%s""",
        [f["log_date"], new_hours, new_svc, f.get("tool_assembly", ""), f.get("note", ""), log_id],
    )
    db.execute(
        "UPDATE units SET circulation_hours = circulation_hours + %s, service_count = service_count + %s WHERE id = %s",
        [hours_delta, svc_delta, unit_id],
    )
    flash("Запись наработки обновлена.", "ok")
    return redirect(url_for("units.detail", unit_id=unit_id))


@bp.route("/<int:unit_id>/usage/<int:log_id>/delete", methods=("POST",))
@roles_required("admin")
def delete_usage(unit_id, log_id):
    log = db.query_one("SELECT * FROM usage_logs WHERE id = %s AND unit_id = %s", [log_id, unit_id])
    if not log:
        flash("Запись наработки не найдена.", "error")
        return redirect(url_for("units.detail", unit_id=unit_id))
    if log["source_tool_usage_log_id"]:
        flash("Эта запись — зеркало наработки инструмента, удалите её на странице инструмента.", "error")
        return redirect(url_for("units.detail", unit_id=unit_id))
    db.execute(
        "UPDATE units SET circulation_hours = circulation_hours - %s, service_count = service_count - %s WHERE id = %s",
        [log["hours_added"], log["service_count_added"], unit_id],
    )
    db.execute("DELETE FROM usage_logs WHERE id = %s", [log_id])
    flash("Запись наработки удалена.", "ok")
    return redirect(url_for("units.detail", unit_id=unit_id))


@bp.route("/<int:unit_id>/writeoff", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def writeoff(unit_id):
    unit = db.query_one(
        """SELECT u.*, p.part_name, p.part_number FROM units u JOIN parts p ON p.id=u.part_id WHERE u.id=%s""",
        [unit_id],
    )
    if not unit:
        flash("Компонент не найден.", "error")
        return redirect(url_for("units.list_units"))

    if request.method == "POST":
        f = request.form
        db.execute(
            """INSERT INTO write_offs (part_id, unit_id, receipt_id, quantity, write_off_date, reason, job_id, act_number, note, created_by)
               VALUES (%s,%s,%s,1,%s,%s,%s,%s,%s,%s)""",
            [unit["part_id"], unit_id, unit.get("receipt_id"), f["write_off_date"], f["reason"],
             f.get("job_id") or None, f.get("act_number", ""), f.get("note", ""), g.user["id"]],
        )
        if unit.get("receipt_id"):
            consume_from_batch(unit["receipt_id"], 1)
        db.execute("UPDATE units SET status = 'written_off' WHERE id = %s", [unit_id])
        flash(f"Компонент {unit['serial_number']} списан.", "ok")
        return redirect(url_for("units.detail", unit_id=unit_id))

    recent_jobs = db.query_all(
        "SELECT id, job_date, job_type, title, tool_assembly FROM service_jobs ORDER BY job_date DESC, id DESC LIMIT 20"
    )
    return render_template("units/writeoff.html", unit=unit, recent_jobs=recent_jobs)
