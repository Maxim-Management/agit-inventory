import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from . import db
from .auth import login_required, roles_required
from .analytics import REASON_LABELS
from .stock import consume_from_batch, open_batches_for_part

bp = Blueprint("writeoffs", __name__, url_prefix="/write-offs")


@bp.route("/")
@login_required
def list_writeoffs():
    reason = request.args.get("reason", "").strip()
    sql = """
        SELECT w.*, u.serial_number, p.part_name, p.part_number
        FROM write_offs w
        JOIN parts p ON p.id = w.part_id
        LEFT JOIN units u ON u.id = w.unit_id
        WHERE 1=1
    """
    params = []
    if reason:
        sql += " AND w.reason = %s"
        params.append(reason)
    sql += " ORDER BY w.write_off_date DESC, w.id DESC LIMIT 500"
    write_offs = db.query_all(sql, params)
    return render_template("writeoffs/list.html", write_offs=write_offs, reason=reason, reason_labels=REASON_LABELS)


@bp.route("/new", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def new_writeoff():
    q = request.args.get("q", "").strip()
    candidates = []
    if q:
        candidates = db.query_all(
            """SELECT u.id, u.serial_number, p.part_name, p.part_number, u.status
               FROM units u JOIN parts p ON p.id = u.part_id
               WHERE u.status = 'in_stock' AND (u.serial_number LIKE %s OR p.part_name LIKE %s)
               ORDER BY u.serial_number LIMIT 30""",
            [f"%{q}%", f"%{q}%"],
        )

    if request.method == "POST":
        f = request.form
        unit_id = f["unit_id"]
        unit = db.query_one("SELECT part_id, receipt_id FROM units WHERE id = %s", [unit_id])
        db.execute(
            """INSERT INTO write_offs (part_id, unit_id, receipt_id, quantity, write_off_date, reason, act_number, note, created_by)
               VALUES (%s,%s,%s,1,%s,%s,%s,%s,%s)""",
            [unit["part_id"], unit_id, unit.get("receipt_id"), f["write_off_date"], f["reason"],
             f.get("act_number", ""), f.get("note", ""), g.user["id"]],
        )
        if unit.get("receipt_id"):
            consume_from_batch(unit["receipt_id"], 1)
        db.execute("UPDATE units SET status = 'written_off' WHERE id = %s", [unit_id])
        flash("Списание зарегистрировано.", "ok")
        return redirect(url_for("writeoffs.list_writeoffs"))

    return render_template("writeoffs/new.html", q=q, candidates=candidates, reason_labels=REASON_LABELS)


@bp.route("/bulk", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def new_bulk_writeoff():
    """Списание несерийного расходника (масло, уплотнения и т.п.) по количеству —
    с выбором партии поступления, из которой списывается остаток."""
    preselect_part_id = request.args.get("part_id", type=int)
    parts = db.query_all(
        "SELECT id, part_name, part_number, tool_size FROM parts WHERE is_serialized = %s ORDER BY part_name",
        [False],
    )
    batches_by_part = {p["id"]: open_batches_for_part(p["id"]) for p in parts}

    if request.method == "POST":
        f = request.form
        qty = float(f.get("quantity") or 0)
        part_id = f["part_id"]
        receipt_id = f.get("receipt_id") or None
        if not receipt_id:
            batches = open_batches_for_part(part_id)
            receipt_id = batches[0]["id"] if batches else None
        if qty <= 0:
            flash("Количество должно быть больше нуля.", "error")
        else:
            db.execute(
                """INSERT INTO write_offs (part_id, unit_id, receipt_id, quantity, write_off_date, reason, act_number, note, created_by)
                   VALUES (%s,NULL,%s,%s,%s,%s,%s,%s,%s)""",
                [part_id, receipt_id, qty, f["write_off_date"], f["reason"], f.get("act_number", ""),
                 f.get("note", ""), g.user["id"]],
            )
            if receipt_id:
                consume_from_batch(receipt_id, qty)
            flash("Списание расходника зарегистрировано.", "ok")
            return redirect(url_for("writeoffs.list_writeoffs"))

    return render_template(
        "writeoffs/bulk.html", parts=parts, reason_labels=REASON_LABELS, preselect_part_id=preselect_part_id,
        batches_by_part_json=json.dumps({str(pid): [
            {"id": b["id"], "label": f"{b.get('batch_serial_number') or ('партия #' + str(b['id']))} · "
                                      f"{b.get('receipt_date') or ''} · остаток {float(b['remaining_quantity']):g}"}
            for b in batches
        ] for pid, batches in batches_by_part.items()}),
    )
