from flask import Blueprint, render_template, request, redirect, url_for, flash

from . import db
from .auth import login_required, roles_required
from .stock import stock_map, part_stock_value, avg_exchange_rate_all_receipts, guaranteed_resource_hours
from .costing import part_unit_cost_rub

bp = Blueprint("parts", __name__, url_prefix="/parts")

UNIT_STATUS_LABELS = {
    "in_stock": "На складе",
    "installed": "В эксплуатации",
    "paired": "В паре",
    "written_off": "Списан",
}


@bp.route("/")
@login_required
def list_parts():
    """Единый раздел «Комплектующие»: серийные компоненты (roторы, статоры,
    корпусные детали — каждый со своим серийным номером, из units) и
    несерийные расходники (масло, уплотнения и т.п. — одна строка на
    деталь, из parts) в одной таблице, в порядке: типоразмер, наименование,
    партийный номер, серийный номер, статус, наработка, применение на
    инструменте, комментарии."""
    q = request.args.get("q", "").strip()
    tool_size = request.args.get("tool_size", "").strip()
    status = request.args.get("status", "").strip()

    rows = []

    # --- серийные компоненты: одна строка на физическую единицу ---
    unit_rows = db.query_all(
        """SELECT u.id AS unit_id, u.serial_number, u.status, u.circulation_hours,
                  u.remarks, u.installed_on, t.serial_number AS tool_serial, t.id AS tool_id,
                  p.id AS part_id, p.tool_size, p.part_name, p.part_number
           FROM units u
           JOIN parts p ON p.id = u.part_id
           LEFT JOIN tools t ON t.id = u.installed_on_tool_id
           ORDER BY p.part_name, u.serial_number"""
    )
    for u in unit_rows:
        tool_label = u["tool_serial"] or u["installed_on"] or ""
        rows.append({
            "part_id": u["part_id"], "unit_id": u["unit_id"],
            "tool_size": u["tool_size"], "part_name": u["part_name"], "part_number": u["part_number"],
            "serial_number": u["serial_number"],
            "status": u["status"], "status_label": True,
            "hours": u["circulation_hours"],
            "tool_label": tool_label, "tool_id": u["tool_id"],
            "comments": u["remarks"],
            "low_stock": False,
        })

    # --- несерийные расходники: одна строка на деталь, остаток вместо статуса ---
    stock = stock_map()
    part_rows = db.query_all(
        "SELECT id AS part_id, tool_size, part_name, part_number, specification, min_stock_qty "
        "FROM parts WHERE is_serialized = %s ORDER BY part_name",
        [False],
    )
    for p in part_rows:
        in_stock = stock.get(p["part_id"], 0)
        rows.append({
            "part_id": p["part_id"], "unit_id": None,
            "tool_size": p["tool_size"], "part_name": p["part_name"], "part_number": p["part_number"],
            "serial_number": "",
            "status": None, "status_label": False, "in_stock": in_stock,
            "hours": None,
            "tool_label": "", "tool_id": None,
            "comments": p["specification"],
            "low_stock": in_stock < p["min_stock_qty"],
        })

    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r["part_name"] or "").lower()
                or ql in (r["part_number"] or "").lower()
                or ql in (r["serial_number"] or "").lower()]
    if tool_size:
        rows = [r for r in rows if r["tool_size"] == tool_size]
    if status:
        rows = [r for r in rows if r["status"] == status]

    rows.sort(key=lambda r: (r["part_name"] or "", r["serial_number"] or ""))

    tool_sizes = [r["tool_size"] for r in db.query_all(
        "SELECT DISTINCT tool_size FROM parts WHERE tool_size != '' ORDER BY tool_size")]

    return render_template(
        "parts/list.html", rows=rows, q=q, tool_size=tool_size, status=status, tool_sizes=tool_sizes,
        status_labels=UNIT_STATUS_LABELS,
    )


@bp.route("/new", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def new_part():
    if request.method == "POST":
        f = request.form
        try:
            db.execute(
                """INSERT INTO parts (tool_size, part_name, part_number, category, specification,
                                       unit_weight_kg, standard_cost_cny, exchange_rate, customs_duty_percent,
                                       unit_transfer_price_rub, min_stock_qty, is_serialized, opening_balance_qty)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [f.get("tool_size", ""), f["part_name"], f["part_number"], f.get("category", "other"),
                 f.get("specification", ""), f.get("unit_weight_kg") or None,
                 f.get("standard_cost_cny") or None, f.get("exchange_rate") or None,
                 f.get("customs_duty_percent") or None, f.get("unit_transfer_price_rub") or None,
                 int(f.get("min_stock_qty") or 0), f.get("is_serialized") == "on",
                 float(f.get("opening_balance_qty") or 0)],
            )
        except Exception as e:
            flash(f"Не удалось создать деталь: {e}", "error")
            return render_template("parts/new.html", form=f)
        flash("Деталь добавлена в справочник.", "ok")
        return redirect(url_for("parts.list_parts"))
    return render_template("parts/new.html", form={})


@bp.route("/<int:part_id>/edit", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def edit_part(part_id):
    part = db.query_one("SELECT * FROM parts WHERE id = %s", [part_id])
    if not part:
        flash("Деталь не найдена.", "error")
        return redirect(url_for("parts.list_parts"))

    if request.method == "POST":
        f = request.form
        db.execute(
            """UPDATE parts SET tool_size=%s, part_name=%s, category=%s, specification=%s,
                                 unit_weight_kg=%s, standard_cost_cny=%s, exchange_rate=%s,
                                 customs_duty_percent=%s, unit_transfer_price_rub=%s,
                                 min_stock_qty=%s, is_serialized=%s, opening_balance_qty=%s
               WHERE id=%s""",
            [f.get("tool_size", ""), f["part_name"], f.get("category", "other"), f.get("specification", ""),
             f.get("unit_weight_kg") or None, f.get("standard_cost_cny") or None,
             f.get("exchange_rate") or None, f.get("customs_duty_percent") or None,
             f.get("unit_transfer_price_rub") or None, int(f.get("min_stock_qty") or 0),
             f.get("is_serialized") == "on", float(f.get("opening_balance_qty") or 0), part_id],
        )
        flash("Деталь обновлена.", "ok")
        return redirect(url_for("parts.detail", part_id=part_id))

    return render_template("parts/edit.html", part=part)


@bp.route("/<int:part_id>/min-stock", methods=("POST",))
@roles_required("admin", "engineer")
def update_min_stock(part_id):
    try:
        min_stock = int(request.form.get("min_stock_qty") or 0)
    except ValueError:
        min_stock = 0
    db.execute("UPDATE parts SET min_stock_qty = %s WHERE id = %s", [min_stock, part_id])
    flash("Неснижаемый остаток обновлён.", "ok")
    return redirect(request.referrer or url_for("parts.list_parts"))


@bp.route("/<int:part_id>")
@login_required
def detail(part_id):
    part = db.query_one("SELECT * FROM parts WHERE id = %s", [part_id])
    if not part:
        flash("Деталь не найдена.", "error")
        return redirect(url_for("parts.list_parts"))

    part["current_stock"] = stock_map().get(part_id, 0)
    part["unit_cost_rub"] = part_unit_cost_rub(part)
    part["stock_value"] = part_stock_value(part_id)
    part["avg_exchange_rate_receipts"] = avg_exchange_rate_all_receipts(part_id)
    part["guaranteed_resource_hours"] = guaranteed_resource_hours(part_id)

    units = db.query_all(
        "SELECT * FROM units WHERE part_id = %s ORDER BY status, serial_number", [part_id]
    )

    ledger = []
    if not part["is_serialized"]:
        receipts = db.query_all(
            """SELECT receipt_date AS d, quantity AS qty, order_ref, note,
                      date_mfg, exchange_rate, total_cost_cny
               FROM receipts WHERE part_id = %s""",
            [part_id],
        )
        for r in receipts:
            extra = []
            if r.get("date_mfg"):
                extra.append(f"пр-во {r['date_mfg']}")
            if r.get("exchange_rate") is not None:
                extra.append(f"курс {r['exchange_rate']:g}")
            if r.get("total_cost_cny") is not None:
                extra.append(f"{r['total_cost_cny']:g} CNY")
            base = r["order_ref"] or r["note"] or ""
            detail = " · ".join([p for p in [base] + extra if p])
            ledger.append({"date": r["d"], "kind": "Поступление", "qty": float(r["qty"]), "detail": detail})
        write_offs = db.query_all(
            """SELECT write_off_date AS d, quantity AS qty, reason, note FROM write_offs
               WHERE part_id = %s AND unit_id IS NULL""",
            [part_id],
        )
        for w in write_offs:
            ledger.append({"date": w["d"], "kind": "Списание", "qty": -float(w["qty"]),
                            "detail": w["reason"]})
        ledger.sort(key=lambda x: x["date"] or "")

    return render_template("parts/detail.html", part=part, units=units, ledger=ledger)
