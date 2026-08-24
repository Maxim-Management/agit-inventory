from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from . import db
from .auth import login_required, roles_required
from .costing import unit_cost_rub

bp = Blueprint("receipts", __name__, url_prefix="/receipts")


def _sync_part_costing(part_id, cost_cny, exchange_rate, transfer_price_rub):
    """После сохранения поступления обновляет в карточке детали "текущие"
    (последнего поступления) составляющие стоимости за единицу — себестоимость
    может отличаться от партии к партии, поэтому каждое новое поступление
    актуализирует их. Обновляет только те поля, для которых в поступлении
    реально указано значение (эти поля справочные и необязательные) — чтобы
    не затирать уже сохранённые данные пустыми. Таможенная пошлина сюда
    намеренно не входит — она атрибут самой позиции (parts.customs_duty_percent),
    одна и та же для всех партий, и правится только вручную в карточке детали
    (см. routes_parts.py)."""
    sets, params = [], []
    if cost_cny is not None:
        sets.append("standard_cost_cny = %s")
        params.append(cost_cny)
    if exchange_rate is not None:
        sets.append("exchange_rate = %s")
        params.append(exchange_rate)
    if transfer_price_rub is not None:
        sets.append("unit_transfer_price_rub = %s")
        params.append(transfer_price_rub)
    if not sets:
        return
    params.append(part_id)
    db.execute(f"UPDATE parts SET {', '.join(sets)} WHERE id = %s", params)


@bp.route("/")
@login_required
def list_receipts():
    receipts = db.query_all(
        """SELECT r.*, p.part_name, p.part_number, p.customs_duty_percent
           FROM receipts r
           JOIN parts p ON p.id = r.part_id
           ORDER BY r.receipt_date DESC, r.id DESC LIMIT 500"""
    )
    receipt_ids = [r["id"] for r in receipts]
    serials_by_receipt = {}
    if receipt_ids:
        placeholders = ",".join(["%s"] * len(receipt_ids))
        unit_rows = db.query_all(
            f"SELECT receipt_id, serial_number FROM units WHERE receipt_id IN ({placeholders}) ORDER BY serial_number",
            receipt_ids,
        )
        for u in unit_rows:
            serials_by_receipt.setdefault(u["receipt_id"], []).append(u["serial_number"])

    for r in receipts:
        # NUMERIC-колонки на Postgres возвращаются как decimal.Decimal — приводим
        # к float ДО арифметики, иначе Decimal/float или Decimal*float падает с
        # TypeError (в SQLite это же значение уже float, там бага незаметна).
        qty = float(r["quantity"] or 0)
        total_cost_cny = float(r["total_cost_cny"]) if r["total_cost_cny"] is not None else None
        cost_cny_per_unit = (total_cost_cny / qty) if (total_cost_cny is not None and qty) else total_cost_cny
        r["unit_cost_rub"] = unit_cost_rub(cost_cny_per_unit, r["exchange_rate"], r["customs_duty_percent"], r["transfer_price_rub"])
        r["serials"] = serials_by_receipt.get(r["id"], [])
    return render_template("receipts/list.html", receipts=receipts)


@bp.route("/new", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def new_receipt():
    parts = db.query_all("SELECT * FROM parts ORDER BY part_name")
    if request.method == "POST":
        f = request.form
        part_id = f["part_id"]
        qty = float(f.get("quantity") or 1)
        serials_raw = f.get("serial_numbers", "").strip()
        serials = [s.strip() for s in serials_raw.splitlines() if s.strip()]
        date_mfg = f.get("date_mfg", "")
        batch_number = f.get("batch_number", "").strip()
        # Таможенная пошлина здесь НЕ вводится — она атрибут позиции
        # (parts.customs_duty_percent, редактируется в карточке детали) и
        # одна и та же для всех партий этой детали, см. _sync_part_costing().
        exchange_rate = float(f["exchange_rate"]) if f.get("exchange_rate") else None
        total_cost_cny = float(f["total_cost_cny"]) if f.get("total_cost_cny") else None
        transfer_price_rub = float(f["transfer_price_rub"]) if f.get("transfer_price_rub") else None

        if serials:
            # Одна ПАРТИЯ поступления = одна строка receipts, даже если в ней
            # сразу несколько серийных номеров — раньше на каждый серийный
            # номер создавалась отдельная строка с задублированными данными
            # партии (курс/стоимость), теперь остаток и стоимость считаются
            # по партии в целом (см. app/stock.py).
            qty_batch = len(serials)
            receipt_id = db.execute_returning_id(
                """INSERT INTO receipts (part_id, quantity, remaining_quantity, receipt_date, order_ref,
                                          batch_serial_number, date_mfg,
                                          exchange_rate, total_cost_cny, transfer_price_rub, note, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                [part_id, qty_batch, qty_batch, f["receipt_date"], f.get("order_ref", ""),
                 batch_number, date_mfg, exchange_rate, total_cost_cny,
                 transfer_price_rub, f.get("note", ""), g.user["id"]],
            )
            created = 0
            for serial in serials:
                db.execute(
                    """INSERT INTO units (part_id, serial_number, date_mfg, status, receipt_id)
                       VALUES (%s,%s,%s,'in_stock',%s)""",
                    [part_id, serial, date_mfg, receipt_id],
                )
                created += 1
            cost_cny_per_unit = (total_cost_cny / qty_batch) if (total_cost_cny is not None and qty_batch) else total_cost_cny
            _sync_part_costing(part_id, cost_cny_per_unit, exchange_rate, transfer_price_rub)
            flash(f"Оприходовано серийных единиц: {created} (партия {batch_number or '№ не указан'}).", "ok")
        else:
            db.execute(
                """INSERT INTO receipts (part_id, quantity, remaining_quantity, receipt_date, order_ref,
                                          batch_serial_number, date_mfg, exchange_rate,
                                          total_cost_cny, transfer_price_rub, note, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [part_id, qty, qty, f["receipt_date"], f.get("order_ref", ""), batch_number,
                 date_mfg, exchange_rate, total_cost_cny,
                 transfer_price_rub, f.get("note", ""), g.user["id"]],
            )
            cost_cny_per_unit = (total_cost_cny / qty) if (total_cost_cny is not None and qty) else total_cost_cny
            _sync_part_costing(part_id, cost_cny_per_unit, exchange_rate, transfer_price_rub)
            flash("Поступление зарегистрировано.", "ok")
        return redirect(url_for("receipts.list_receipts"))
    return render_template("receipts/new.html", parts=parts)
