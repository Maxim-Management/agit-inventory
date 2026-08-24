from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from .auth import login_required, roles_required
from . import customers as customers_mod
from .customers import TOOL_SIZES

bp = Blueprint("customers", __name__, url_prefix="/customers")

# Имена полей формы не могут содержать пробелы/слэши — сопоставляем каждому
# типоразмеру безопасный ключ для input name="work_rate_{key}" и т.п.
SIZE_KEYS = {"4 3/4": "s475", "6 3/4": "s675", "8": "s8"}


def _read_rates_from_form(f):
    """Считывает ставки по всем TOOL_SIZES из полей формы вида
    work_rate_{key}/work_rate_unit_{key}/standby_rate_{key}."""
    rates = {}
    for size in TOOL_SIZES:
        key = SIZE_KEYS[size]
        rates[size] = {
            "work_rate": float(f.get(f"work_rate_{key}") or 0),
            "work_rate_unit": f.get(f"work_rate_unit_{key}", "hour"),
            "standby_rate_rub_per_day": float(f.get(f"standby_rate_{key}") or 0),
        }
    return rates


@bp.route("/")
@login_required
def list_view():
    q = request.args.get("q", "").strip()
    rows = customers_mod.list_customers(q=q or None)
    for c in rows:
        c["revenue_total"] = customers_mod.customer_revenue_total(c["id"])
        rates = customers_mod.get_customer_rates_map(c["id"])
        c["rates_summary"] = [
            {"size": size, "work_rate": r["work_rate"], "unit": r["work_rate_unit"],
             "standby_rate_rub_per_day": r["standby_rate_rub_per_day"]}
            for size, r in rates.items()
        ]
    return render_template("customers/list.html", customers=rows, q=q,
                            work_rate_unit_labels=customers_mod.WORK_RATE_UNIT_LABELS)


@bp.route("/new", methods=("GET", "POST"))
@roles_required("admin", "engineer")
def new_customer():
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        if not name:
            flash("Название/наименование заказчика обязательно.", "error")
            return render_template("customers/new.html", form=f, tool_sizes=TOOL_SIZES, size_keys=SIZE_KEYS)
        try:
            customer_id = customers_mod.create_customer(name, f.get("contract_number", ""), f.get("note", ""), g.user["id"])
            for size, rate in _read_rates_from_form(f).items():
                customers_mod.set_customer_rate(customer_id, size, rate["work_rate"], rate["work_rate_unit"],
                                                 rate["standby_rate_rub_per_day"])
        except Exception as e:
            flash(f"Не удалось создать заказчика: {e}", "error")
            return render_template("customers/new.html", form=f, tool_sizes=TOOL_SIZES, size_keys=SIZE_KEYS)
        flash(f"Заказчик «{name}» добавлен.", "ok")
        return redirect(url_for("customers.list_view"))
    return render_template("customers/new.html", form={}, tool_sizes=TOOL_SIZES, size_keys=SIZE_KEYS)


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
            rates = customers_mod.get_customer_rates_map(customer_id)
            return render_template("customers/edit.html", customer=customer, rates=rates,
                                    tool_sizes=TOOL_SIZES, size_keys=SIZE_KEYS)
        customers_mod.update_customer(customer_id, name, f.get("contract_number", ""), f.get("note", ""))
        for size, rate in _read_rates_from_form(f).items():
            customers_mod.set_customer_rate(customer_id, size, rate["work_rate"], rate["work_rate_unit"],
                                             rate["standby_rate_rub_per_day"])
        flash("Карточка заказчика обновлена.", "ok")
        return redirect(url_for("customers.list_view"))
    rates = customers_mod.get_customer_rates_map(customer_id)
    return render_template("customers/edit.html", customer=customer, rates=rates,
                            tool_sizes=TOOL_SIZES, size_keys=SIZE_KEYS)
