from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from .auth import login_required, roles_required
from . import customers as customers_mod

bp = Blueprint("customers", __name__, url_prefix="/customers")


@bp.route("/")
@login_required
def list_view():
    q = request.args.get("q", "").strip()
    rows = customers_mod.list_customers(q=q or None)
    for c in rows:
        c["revenue_total"] = customers_mod.customer_revenue_total(c["id"])
    return render_template("customers/list.html", customers=rows, q=q)


@bp.route("/new", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def new_customer():
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        if not name:
            flash("Название/наименование заказчика обязательно.", "error")
            return render_template("customers/new.html", form=f)
        try:
            customer_id = customers_mod.create_customer(
                name, f.get("contract_number", ""),
                float(f.get("work_rate_rub_per_hour") or 0),
                float(f.get("standby_rate_rub_per_day") or 0),
                f.get("note", ""), g.user["id"],
            )
        except Exception as e:
            flash(f"Не удалось создать заказчика: {e}", "error")
            return render_template("customers/new.html", form=f)
        flash(f"Заказчик «{name}» добавлен.", "ok")
        return redirect(url_for("customers.list_view"))
    return render_template("customers/new.html", form={})


@bp.route("/<int:customer_id>/edit", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def edit_customer(customer_id):
    customer = customers_mod.get_customer(customer_id)
    if not customer:
        flash("Заказчик не найден.", "error")
        return redirect(url_for("customers.list_view"))
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        if not name:
            flash("Название/наименование заказчика обязательно.", "error")
            return render_template("customers/edit.html", customer=customer)
        customers_mod.update_customer(
            customer_id, name, f.get("contract_number", ""),
            float(f.get("work_rate_rub_per_hour") or 0),
            float(f.get("standby_rate_rub_per_day") or 0),
            f.get("note", ""),
        )
        flash("Карточка заказчика обновлена.", "ok")
        return redirect(url_for("customers.list_view"))
    return render_template("customers/edit.html", customer=customer)
