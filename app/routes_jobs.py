import csv
import io
import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, Response

from . import db
from .auth import login_required, roles_required
from .jobs import list_jobs, job_totals, job_write_offs, JOB_TYPE_LABELS
from .analytics import REASON_LABELS
from . import tools as tools_mod
from .stock import consume_from_batch, open_batches_for_part

bp = Blueprint("jobs", __name__, url_prefix="/jobs")


@bp.route("/")
@login_required
def list_view():
    job_type = request.args.get("job_type") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    jobs = list_jobs(job_type=job_type, date_from=date_from, date_to=date_to)
    grand_total = sum(j["total_cost"] for j in jobs)
    return render_template(
        "jobs/list.html", jobs=jobs, job_type=job_type, date_from=date_from, date_to=date_to,
        job_type_labels=JOB_TYPE_LABELS, grand_total=grand_total,
    )


def _unlinked_write_offs():
    """Списания, ещё не привязанные ни к одной работе (job_id IS NULL) —
    источник для окна выбора «списанные комплектующие» при создании новой
    работы: компонент мог быть списан раньше (например, через раздел
    «Списания»), а работу, на которую он ушёл, оформляют только сейчас."""
    return db.query_all(
        """SELECT w.id, w.write_off_date, w.quantity, w.reason, p.part_name, p.part_number, u.serial_number
           FROM write_offs w
           JOIN parts p ON p.id = w.part_id
           LEFT JOIN units u ON u.id = w.unit_id
           WHERE w.job_id IS NULL
           ORDER BY w.write_off_date DESC, w.id DESC LIMIT 50"""
    )


@bp.route("/new", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def new_job():
    tool_list = db.query_all("SELECT id, serial_number, tool_size FROM tools ORDER BY serial_number")
    if request.method == "POST":
        f = request.form
        tool_id = f.get("tool_id") or None
        if not tool_id:
            flash("Выберите инструмент (серийный номер) — работа обязательно должна быть привязана к конкретному инструменту.", "error")
            return render_template("jobs/new.html", job_type_labels=JOB_TYPE_LABELS, tools=tool_list, form=f,
                                    unlinked_write_offs=_unlinked_write_offs(), reason_labels=REASON_LABELS)
        tool = tools_mod.get_tool(tool_id)
        job_id = db.execute_returning_id(
            """INSERT INTO service_jobs (job_type, job_date, tool_id, tool_assembly, title,
                                          work_order_number, performed_by, service_center,
                                          service_center_cost, labor_cost, other_cost, note, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            [f.get("job_type", "repair"), f["job_date"], tool_id, tool["serial_number"] if tool else "",
             f.get("title", ""), f.get("work_order_number", ""), f.get("performed_by", ""),
             f.get("service_center", ""), float(f.get("service_center_cost") or 0), float(f.get("labor_cost") or 0),
             float(f.get("other_cost") or 0), f.get("note", ""), g.user["id"]],
        )
        write_off_ids = [int(i) for i in request.form.getlist("write_off_ids") if i.strip().isdigit()]
        linked = 0
        for woid in write_off_ids:
            linked += db.execute(
                "UPDATE write_offs SET job_id = %s WHERE id = %s AND job_id IS NULL", [job_id, woid]
            )
        msg = "Работа создана."
        if linked:
            msg += f" Привязано ранее списанных комплектующих: {linked}."
        msg += " Теперь можно привязать ещё списанные компоненты."
        flash(msg, "ok")
        return redirect(url_for("jobs.detail", job_id=job_id))
    return render_template("jobs/new.html", job_type_labels=JOB_TYPE_LABELS, tools=tool_list, form={},
                            unlinked_write_offs=_unlinked_write_offs(), reason_labels=REASON_LABELS)


@bp.route("/<int:job_id>")
@login_required
def detail(job_id):
    job = db.query_one(
        """SELECT sj.*, t.serial_number AS tool_serial FROM service_jobs sj
           LEFT JOIN tools t ON t.id = sj.tool_id WHERE sj.id = %s""",
        [job_id],
    )
    if not job:
        flash("Работа не найдена.", "error")
        return redirect(url_for("jobs.list_view"))
    job.update(job_totals(job))
    write_offs = job_write_offs(job_id)

    q = request.args.get("q", "").strip()
    unit_candidates = []
    if q:
        # Ищем и свободные компоненты со склада, и компоненты, уже
        # установленные на ИНСТРУМЕНТЕ этой работы (их тоже можно списать
        # или, если они не под замену, а просто сняты, вернуть на склад —
        # см. кнопку "Перевести на склад" в шаблоне).
        unit_candidates = db.query_all(
            """SELECT u.id, u.serial_number, u.status, p.part_name, p.part_number
               FROM units u JOIN parts p ON p.id = u.part_id
               WHERE (u.serial_number LIKE %s OR p.part_name LIKE %s)
                 AND (u.status = 'in_stock' OR (u.status = 'installed' AND u.installed_on_tool_id = %s))
               ORDER BY u.serial_number LIMIT 20""",
            [f"%{q}%", f"%{q}%", job["tool_id"]],
        )
    bulk_parts = db.query_all(
        "SELECT id, part_name, part_number FROM parts WHERE is_serialized = %s ORDER BY part_name",
        [False],
    )
    batches_by_part_json = json.dumps({str(p["id"]): [
        {"id": b["id"], "label": f"{b.get('batch_serial_number') or ('партия #' + str(b['id']))} · "
                                  f"{b.get('receipt_date') or ''} · остаток {float(b['remaining_quantity']):g}"}
        for b in open_batches_for_part(p["id"])
    ] for p in bulk_parts})
    tool_list = db.query_all("SELECT id, serial_number, tool_size FROM tools ORDER BY serial_number")

    return render_template(
        "jobs/detail.html", job=job, write_offs=write_offs, reason_labels=REASON_LABELS,
        job_type_labels=JOB_TYPE_LABELS, q=q, unit_candidates=unit_candidates, bulk_parts=bulk_parts,
        batches_by_part_json=batches_by_part_json, tools=tool_list,
    )


@bp.route("/<int:job_id>/delete", methods=("POST",))
@roles_required("admin")
def delete_job(job_id):
    job = db.query_one("SELECT * FROM service_jobs WHERE id = %s", [job_id])
    if not job:
        flash("Работа не найдена.", "error")
        return redirect(url_for("jobs.list_view"))
    # Удаление работы отменяет и её списания: компонент возвращается на
    # склад (серийный — статус обратно 'in_stock'; расходник — остаток
    # партии-источника увеличивается обратно), сами записи списания удаляются.
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
    db.execute("DELETE FROM service_jobs WHERE id = %s", [job_id])
    msg = "Работа удалена."
    if restored:
        msg += f" Списанные на неё компоненты ({restored}) возвращены на склад."
    flash(msg, "ok")
    return redirect(url_for("jobs.list_view"))


@bp.route("/<int:job_id>/edit-costs", methods=("POST",))
@roles_required("admin")
def edit_costs(job_id):
    f = request.form
    tool_id = f.get("tool_id") or None
    if not tool_id:
        flash("Работа обязательно должна быть привязана к инструменту.", "error")
        return redirect(url_for("jobs.detail", job_id=job_id))
    tool = tools_mod.get_tool(tool_id)
    db.execute(
        """UPDATE service_jobs SET title=%s, tool_id=%s, tool_assembly=%s,
                                    work_order_number=%s, performed_by=%s, service_center=%s,
                                    service_center_cost=%s, labor_cost=%s, other_cost=%s, note=%s WHERE id=%s""",
        [f.get("title", ""), tool_id, tool["serial_number"] if tool else "",
         f.get("work_order_number", ""), f.get("performed_by", ""), f.get("service_center", ""),
         float(f.get("service_center_cost") or 0),
         float(f.get("labor_cost") or 0), float(f.get("other_cost") or 0), f.get("note", ""), job_id],
    )
    flash("Затраты по работе обновлены.", "ok")
    return redirect(url_for("jobs.detail", job_id=job_id))


@bp.route("/<int:job_id>/consume-unit", methods=("POST",))
@roles_required("admin", "engineer")
def consume_unit(job_id):
    f = request.form
    unit = db.query_one("SELECT * FROM units WHERE id = %s", [f["unit_id"]])
    if not unit:
        flash("Компонент не найден.", "error")
        return redirect(url_for("jobs.detail", job_id=job_id))
    db.execute(
        """INSERT INTO write_offs (part_id, unit_id, receipt_id, quantity, write_off_date, reason, job_id, act_number, note, created_by)
           VALUES (%s,%s,%s,1,%s,%s,%s,%s,%s,%s)""",
        [unit["part_id"], unit["id"], unit.get("receipt_id"), f["write_off_date"], f["reason"], job_id,
         f.get("act_number", ""), f.get("note", ""), g.user["id"]],
    )
    if unit.get("receipt_id"):
        consume_from_batch(unit["receipt_id"], 1)
    # Компонент мог быть установлен на инструменте (списание при ремонте) —
    # снимаем его с инструмента одновременно со списанием.
    db.execute(
        "UPDATE units SET status = 'written_off', installed_on_tool_id = NULL, installed_on = '' WHERE id = %s",
        [unit["id"]],
    )
    flash(f"Компонент {unit['serial_number']} списан на работу.", "ok")
    return redirect(url_for("jobs.detail", job_id=job_id))


@bp.route("/<int:job_id>/transfer-unit", methods=("POST",))
@roles_required("admin", "engineer")
def transfer_unit(job_id):
    """Снять установленный на инструменте этой работы компонент и вернуть
    его на склад (в отличие от consume_unit — без списания: компонент не
    признан дефектным, просто снят, например, при плановой замене)."""
    f = request.form
    unit = db.query_one("SELECT * FROM units WHERE id = %s", [f["unit_id"]])
    if not unit:
        flash("Компонент не найден.", "error")
        return redirect(url_for("jobs.detail", job_id=job_id))
    tools_mod.remove_unit(unit["id"])
    flash(f"Компонент {unit['serial_number']} снят с инструмента и возвращён на склад (без списания).", "ok")
    return redirect(url_for("jobs.detail", job_id=job_id))


@bp.route("/<int:job_id>/consume-bulk", methods=("POST",))
@roles_required("admin", "engineer")
def consume_bulk(job_id):
    f = request.form
    part_id = f["part_id"]
    qty = float(f.get("quantity") or 0)
    if qty <= 0:
        flash("Количество должно быть больше нуля.", "error")
        return redirect(url_for("jobs.detail", job_id=job_id))
    receipt_id = f.get("receipt_id") or None
    if not receipt_id:
        batches = open_batches_for_part(part_id)
        receipt_id = batches[0]["id"] if batches else None
    db.execute(
        """INSERT INTO write_offs (part_id, unit_id, receipt_id, quantity, write_off_date, reason, job_id, act_number, note, created_by)
           VALUES (%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [part_id, receipt_id, qty, f["write_off_date"], f["reason"], job_id,
         f.get("act_number", ""), f.get("note", ""), g.user["id"]],
    )
    if receipt_id:
        consume_from_batch(receipt_id, qty)
    flash("Расходник списан на работу.", "ok")
    return redirect(url_for("jobs.detail", job_id=job_id))


@bp.route("/report")
@login_required
def report():
    job_type = request.args.get("job_type") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    jobs = list_jobs(job_type=job_type, date_from=date_from, date_to=date_to)

    totals = {
        "jobs_count": len(jobs),
        "parts_cost": round(sum(j["parts_cost"] for j in jobs), 2),
        "service_center_cost": round(sum(j["service_center_cost"] for j in jobs), 2),
        "labor_cost": round(sum(j["labor_cost"] for j in jobs), 2),
        "other_cost": round(sum(j["other_cost"] for j in jobs), 2),
        "total_cost": round(sum(j["total_cost"] for j in jobs), 2),
    }

    by_type = {}
    for j in jobs:
        t = j["job_type"]
        by_type.setdefault(t, {"count": 0, "total_cost": 0.0})
        by_type[t]["count"] += 1
        by_type[t]["total_cost"] += j["total_cost"]

    return render_template(
        "jobs/report.html", jobs=jobs, totals=totals, by_type=by_type,
        job_type_labels=JOB_TYPE_LABELS, job_type=job_type, date_from=date_from, date_to=date_to,
    )


@bp.route("/report/export.csv")
@login_required
def export_report_csv():
    job_type = request.args.get("job_type") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    jobs = list_jobs(job_type=job_type, date_from=date_from, date_to=date_to)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Дата", "Тип", "Сборка", "Название", "Стоимость деталей, RUB",
                      "Сервисный центр, RUB", "Персонал, RUB", "Прочее, RUB", "Итого, RUB"])
    for j in jobs:
        writer.writerow([
            j["job_date"], JOB_TYPE_LABELS.get(j["job_type"], j["job_type"]), j["tool_assembly"], j["title"],
            j["parts_cost"], j["service_center_cost"], j["labor_cost"], j["other_cost"], j["total_cost"],
        ])

    return Response(
        buf.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=jobs_report.csv"},
    )
