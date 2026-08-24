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


def _f(value):
    """float(value) с учётом того, что пустая строка из формы означает
    "не заполнено" — возвращает None, а не бросает исключение."""
    if value is None:
        return None
    value = value.strip() if isinstance(value, str) else value
    if value == "":
        return None
    return float(value)


@bp.route("/new", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def new_receipt():
    parts = db.query_all("SELECT * FROM parts ORDER BY part_name")
    if request.method == "POST":
        f = request.form

        # --- поля заказа (общие для ВСЕХ позиций этого поступления) ---
        receipt_date = f["receipt_date"]
        order_ref = f.get("order_ref", "").strip()
        order_total_weight_kg = _f(f.get("order_total_weight_kg"))
        order_total_shipping_cost_rub = _f(f.get("order_total_shipping_cost_rub"))
        exchange_rate = _f(f.get("exchange_rate"))

        # --- позиции: параллельные списки, одна строка формы = один индекс ---
        part_ids = f.getlist("position_part_id")
        quantities = f.getlist("position_quantity")
        total_costs_cny = f.getlist("position_total_cost_cny")
        weights_kg = f.getlist("position_weight_kg")
        dates_mfg = f.getlist("position_date_mfg")
        serials_lists = f.getlist("position_serial_numbers")

        def _at(lst, i, default=""):
            return lst[i] if i < len(lst) else default

        positions_created = 0
        units_created = 0
        for i, part_id in enumerate(part_ids):
            part_id = (part_id or "").strip()
            if not part_id:
                continue

            total_cost_cny = _f(_at(total_costs_cny, i))
            weight_kg = _f(_at(weights_kg, i))
            date_mfg = _at(dates_mfg, i, "").strip()
            serials_raw = _at(serials_lists, i, "")
            serials = [s.strip() for s in serials_raw.splitlines() if s.strip()]

            if serials:
                # Серийная деталь: количество = число указанных серийных
                # номеров, значение поля "Количество" в этом случае игнорируется.
                qty = float(len(serials))
            else:
                qty = _f(_at(quantities, i)) or 1.0

            # Трансфер прайс за единицу этой позиции — доля от общих затрат
            # на доставку заказа, пропорциональная доле веса позиции в общем
            # весе заказа, делённая на количество единиц позиции (стоимость
            # за единицу считается по формуле в app/costing.py).
            transfer_price_rub = None
            if weight_kg is not None and order_total_weight_kg and order_total_shipping_cost_rub is not None and qty:
                position_transfer_total = order_total_shipping_cost_rub * (weight_kg / order_total_weight_kg)
                transfer_price_rub = position_transfer_total / qty

            cost_cny_per_unit = (total_cost_cny / qty) if (total_cost_cny is not None and qty) else total_cost_cny

            if serials:
                # Одна ПОЗИЦИЯ = одна строка receipts, даже если в ней сразу
                # несколько серийных номеров — остаток и стоимость считаются
                # по позиции в целом (см. app/stock.py).
                receipt_id = db.execute_returning_id(
                    """INSERT INTO receipts (part_id, quantity, remaining_quantity, receipt_date, order_ref,
                                              date_mfg, exchange_rate, total_cost_cny,
                                              weight_kg, order_total_weight_kg, order_total_shipping_cost_rub,
                                              transfer_price_rub, note, created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    [part_id, qty, qty, receipt_date, order_ref,
                     date_mfg, exchange_rate, total_cost_cny,
                     weight_kg, order_total_weight_kg, order_total_shipping_cost_rub,
                     transfer_price_rub, f.get("note", ""), g.user["id"]],
                )
                for serial in serials:
                    db.execute(
                        """INSERT INTO units (part_id, serial_number, date_mfg, status, receipt_id)
                           VALUES (%s,%s,%s,'in_stock',%s)""",
                        [part_id, serial, date_mfg, receipt_id],
                    )
                    units_created += 1
            else:
                db.execute(
                    """INSERT INTO receipts (part_id, quantity, remaining_quantity, receipt_date, order_ref,
                                              date_mfg, exchange_rate, total_cost_cny,
                                              weight_kg, order_total_weight_kg, order_total_shipping_cost_rub,
                                              transfer_price_rub, note, created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [part_id, qty, qty, receipt_date, order_ref,
                     date_mfg, exchange_rate, total_cost_cny,
                     weight_kg, order_total_weight_kg, order_total_shipping_cost_rub,
                     transfer_price_rub, f.get("note", ""), g.user["id"]],
                )

            _sync_part_costing(part_id, cost_cny_per_unit, exchange_rate, transfer_price_rub)
            positions_created += 1

        if positions_created == 0:
            flash("Не указано ни одной позиции — поступление не сохранено.", "error")
            return render_template("receipts/new.html", parts=parts)

        msg = f"Поступление зарегистрировано: позиций {positions_created}"
        if units_created:
            msg += f", серийных единиц оприходовано {units_created}"
        msg += "."
        flash(msg, "ok")
        return redirect(url_for("receipts.list_receipts"))
    return render_template("receipts/new.html", parts=parts)
