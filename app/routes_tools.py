import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from . import db
from .auth import login_required, roles_required
from . import tools as tools_mod
from .tools import STATUS_LABELS
from . import customers as customers_mod

bp = Blueprint("tools", __name__, url_prefix="/tools")


@bp.route("/")
@login_required
def list_view():
    status = request.args.get("status") or None
    q = request.args.get("q") or None
    tool_list = tools_mod.list_tools(status=status, q=q)
    return render_template("tools/list.html", tools=tool_list, status=status, q=q, status_labels=STATUS_LABELS)


@bp.route("/new", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def new_tool():
    if request.method == "POST":
        f = request.form
        serial_number = f.get("serial_number", "").strip()
        if not serial_number:
            flash("Серийный номер обязателен.", "error")
            return render_template("tools/new.html", status_labels=STATUS_LABELS, form=f)
        try:
            tool_id = tools_mod.create_tool(
                serial_number, f.get("tool_size", ""), f.get("status", "active"),
                f.get("commissioned_date") or None, f.get("cost_rub") or None,
                f.get("location", ""), f.get("note", ""), g.user["id"],
            )
        except Exception as e:
            flash(f"Не удалось создать инструмент: {e}", "error")
            return render_template("tools/new.html", status_labels=STATUS_LABELS, form=f)
        flash(f"Инструмент {serial_number} зарегистрирован.", "ok")
        return redirect(url_for("tools.detail", tool_id=tool_id))
    return render_template("tools/new.html", status_labels=STATUS_LABELS, form={})


@bp.route("/<int:tool_id>")
@login_required
def detail(tool_id):
    tool = tools_mod.get_tool(tool_id)
    if not tool:
        flash("Инструмент не найден.", "error")
        return redirect(url_for("tools.list_view"))
    tool.update(tools_mod.tool_totals(tool_id))
    tool["tool_name"] = tools_mod.tool_display_name(tool["tool_size"])

    units = tools_mod.installed_units(tool_id)
    usage_history = tools_mod.tool_usage_history(tool_id)
    revenue_history = tools_mod.tool_revenue_history(tool_id)
    jobs = tools_mod.tool_jobs(tool_id)

    cumulative = []
    total_hours = 0.0
    for log in usage_history:
        total_hours += float(log["hours_added"] or 0)
        cumulative.append({"date": log["log_date"], "hours": total_hours})

    q = request.args.get("q", "").strip()
    unit_candidates = []
    if q:
        unit_candidates = db.query_all(
            """SELECT u.id, u.serial_number, p.part_name, p.part_number
               FROM units u JOIN parts p ON p.id = u.part_id
               WHERE u.status = 'in_stock' AND (u.serial_number LIKE %s OR p.part_name LIKE %s)
               ORDER BY u.serial_number LIMIT 20""",
            [f"%{q}%", f"%{q}%"],
        )

    customers = customers_mod.list_customers()
    customers_json = json.dumps({
        str(c["id"]): {
            "work_rate": float(c["work_rate_rub_per_hour"] or 0),
            "standby_rate": float(c["standby_rate_rub_per_day"] or 0),
        } for c in customers
    })

    return render_template(
        "tools/detail.html", tool=tool, units=units, usage_history=usage_history,
        revenue_history=revenue_history, jobs=jobs, cumulative=cumulative,
        status_labels=STATUS_LABELS, q=q, unit_candidates=unit_candidates,
        customers=customers, customers_json=customers_json,
    )


@bp.route("/<int:tool_id>/edit", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def edit_tool(tool_id):
    tool = tools_mod.get_tool(tool_id)
    if not tool:
        flash("Инструмент не найден.", "error")
        return redirect(url_for("tools.list_view"))
    if request.method == "POST":
        f = request.form
        db.execute(
            """UPDATE tools SET tool_size=%s, status=%s, commissioned_date=%s, cost_rub=%s, location=%s, note=%s
               WHERE id=%s""",
            [f.get("tool_size", ""), f.get("status", "active"), f.get("commissioned_date") or None,
             f.get("cost_rub") or None, f.get("location", ""), f.get("note", ""), tool_id],
        )
        flash("Инструмент обновлён.", "ok")
        return redirect(url_for("tools.detail", tool_id=tool_id))
    return render_template("tools/edit.html", tool=tool, status_labels=STATUS_LABELS)


@bp.route("/<int:tool_id>/install", methods=("POST",))
@roles_required("admin", "engineer")
def install(tool_id):
    f = request.form
    unit_id = f.get("unit_id")
    unit = db.query_one("SELECT * FROM units WHERE id = %s", [unit_id])
    if not unit:
        flash("Компонент не найден.", "error")
        return redirect(url_for("tools.detail", tool_id=tool_id))
    if unit["status"] != "in_stock":
        flash("Устанавливать можно только компоненты со статусом «на складе».", "error")
        return redirect(url_for("tools.detail", tool_id=tool_id))
    tools_mod.install_unit(unit_id, tool_id)
    flash(f"Компонент {unit['serial_number']} установлен на инструмент.", "ok")
    return redirect(url_for("tools.detail", tool_id=tool_id))


@bp.route("/<int:tool_id>/uninstall", methods=("POST",))
@roles_required("admin", "engineer")
def uninstall(tool_id):
    unit_id = request.form.get("unit_id")
    unit = db.query_one("SELECT * FROM units WHERE id = %s AND installed_on_tool_id = %s", [unit_id, tool_id])
    if not unit:
        flash("Компонент не найден на этом инструменте.", "error")
        return redirect(url_for("tools.detail", tool_id=tool_id))
    tools_mod.remove_unit(unit_id)
    flash(f"Компонент {unit['serial_number']} снят с инструмента и возвращён на склад.", "ok")
    return redirect(url_for("tools.detail", tool_id=tool_id))


@bp.route("/<int:tool_id>/usage", methods=("POST",))
@roles_required("admin", "engineer")
def add_usage(tool_id):
    f = request.form
    hours = float(f.get("hours_added") or 0)
    if hours <= 0:
        flash("Часы наработки должны быть больше нуля.", "error")
        return redirect(url_for("tools.detail", tool_id=tool_id))
    result = tools_mod.log_tool_usage(tool_id, f["log_date"], hours, f.get("note", ""), g.user["id"])
    flash(f"Наработка +{hours} ч добавлена инструменту и {result['affected']} установленным компонентам.", "ok")
    return redirect(url_for("tools.detail", tool_id=tool_id))


@bp.route("/<int:tool_id>/revenue", methods=("POST",))
@roles_required("admin", "engineer")
def add_revenue(tool_id):
    f = request.form
    customer_id = f.get("customer_id") or None
    if customer_id:
        work_hours = float(f.get("work_hours") or 0)
        standby_days = float(f.get("standby_days") or 0)
        if work_hours <= 0 and standby_days <= 0:
            flash("Укажите количество работы (ч) и/или дежурства (сут.) больше нуля.", "error")
            return redirect(url_for("tools.detail", tool_id=tool_id))
        try:
            amount = tools_mod.log_tool_revenue(
                tool_id, f["revenue_date"], f.get("note", ""), g.user["id"],
                customer_id=customer_id, well_number=f.get("well_number", ""),
                work_hours=work_hours, standby_days=standby_days,
            )
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("tools.detail", tool_id=tool_id))
        msg = f"Выручка {amount:g} ₽ добавлена."
        if work_hours > 0:
            msg += f" Наработка +{work_hours:g} ч перенесена в наработку инструмента."
        flash(msg, "ok")
    else:
        amount = float(f.get("amount") or 0)
        if amount <= 0:
            flash("Сумма выручки должна быть больше нуля.", "error")
            return redirect(url_for("tools.detail", tool_id=tool_id))
        tools_mod.log_tool_revenue(tool_id, f["revenue_date"], f.get("note", ""), g.user["id"],
                                    amount=amount, currency=f.get("currency", "RUB"))
        flash("Выручка добавлена.", "ok")
    return redirect(url_for("tools.detail", tool_id=tool_id))


@bp.route("/<int:tool_id>/usage/<int:log_id>/edit", methods=("POST",))
@roles_required("admin")
def edit_usage(tool_id, log_id):
    f = request.form
    hours = float(f.get("hours_added") or 0)
    if hours <= 0:
        flash("Часы наработки должны быть больше нуля.", "error")
        return redirect(url_for("tools.detail", tool_id=tool_id))
    try:
        tools_mod.edit_tool_usage(tool_id, log_id, f["log_date"], hours, f.get("note", ""))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("tools.detail", tool_id=tool_id))
    flash("Запись наработки обновлена, наработка затронутых компонентов пересчитана.", "ok")
    return redirect(url_for("tools.detail", tool_id=tool_id))


@bp.route("/<int:tool_id>/usage/<int:log_id>/delete", methods=("POST",))
@roles_required("admin")
def delete_usage(tool_id, log_id):
    try:
        tools_mod.delete_tool_usage(tool_id, log_id)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("tools.detail", tool_id=tool_id))
    flash("Запись наработки удалена, наработка затронутых компонентов пересчитана.", "ok")
    return redirect(url_for("tools.detail", tool_id=tool_id))


@bp.route("/<int:tool_id>/revenue/<int:revenue_id>/edit", methods=("POST",))
@roles_required("admin")
def edit_revenue(tool_id, revenue_id):
    row = db.query_one("SELECT * FROM tool_revenue WHERE id = %s AND tool_id = %s", [revenue_id, tool_id])
    if row and row.get("customer_id"):
        flash("Запись выручки с привязкой к заказчику нельзя править — удалите её и внесите заново.", "error")
        return redirect(url_for("tools.detail", tool_id=tool_id))
    f = request.form
    amount = float(f.get("amount") or 0)
    if amount <= 0:
        flash("Сумма выручки должна быть больше нуля.", "error")
        return redirect(url_for("tools.detail", tool_id=tool_id))
    tools_mod.edit_tool_revenue(tool_id, revenue_id, f["revenue_date"], amount, f.get("note", ""))
    flash("Запись о выручке обновлена.", "ok")
    return redirect(url_for("tools.detail", tool_id=tool_id))


@bp.route("/<int:tool_id>/revenue/<int:revenue_id>/delete", methods=("POST",))
@roles_required("admin")
def delete_revenue(tool_id, revenue_id):
    row = db.query_one("SELECT * FROM tool_revenue WHERE id = %s AND tool_id = %s", [revenue_id, tool_id])
    had_usage_link = bool(row and row.get("usage_log_id"))
    tools_mod.delete_tool_revenue(tool_id, revenue_id)
    msg = "Запись о выручке удалена."
    if had_usage_link:
        msg += " Перенесённая ею наработка откачена."
    flash(msg, "ok")
    return redirect(url_for("tools.detail", tool_id=tool_id))
