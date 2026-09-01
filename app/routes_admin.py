import json
import secrets
from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, Response
from werkzeug.security import generate_password_hash

from . import db
from .auth import roles_required, ROLE_LABELS

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/users")
@roles_required("admin")
def users():
    all_users = db.query_all("SELECT * FROM users ORDER BY created_at")
    return render_template("admin/users.html", users=all_users, role_labels=ROLE_LABELS)


@bp.route("/users/new", methods=("GET", "POST"))
@roles_required("admin")
def new_user():
    if request.method == "POST":
        f = request.form
        email = f["email"].strip().lower()
        temp_password = f.get("password", "").strip() or secrets.token_urlsafe(9)
        try:
            db.execute(
                "INSERT INTO users (email, password_hash, full_name, role) VALUES (%s,%s,%s,%s)",
                [email, generate_password_hash(temp_password), f.get("full_name", ""), f.get("role", "viewer")],
            )
        except Exception as e:
            flash(f"Не удалось создать пользователя: {e}", "error")
            return render_template("admin/new_user.html", form=f, role_labels=ROLE_LABELS)
        flash(f"Пользователь {email} создан. Временный пароль: {temp_password}", "ok")
        return redirect(url_for("admin.users"))
    return render_template("admin/new_user.html", form={}, role_labels=ROLE_LABELS)


@bp.route("/users/<int:user_id>/role", methods=("POST",))
@roles_required("admin")
def change_role(user_id):
    role = request.form["role"]
    db.execute("UPDATE users SET role = %s WHERE id = %s", [role, user_id])
    flash("Роль обновлена.", "ok")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/toggle", methods=("POST",))
@roles_required("admin")
def toggle_active(user_id):
    if g.user["id"] == user_id:
        flash("Нельзя отключить собственную учётную запись.", "error")
        return redirect(url_for("admin.users"))
    user = db.query_one("SELECT * FROM users WHERE id = %s", [user_id])
    new_state = not user["is_active"]
    db.execute("UPDATE users SET is_active = %s WHERE id = %s", [new_state, user_id])
    flash("Статус пользователя обновлён.", "ok")
    return redirect(url_for("admin.users"))


def _json_default(value):
    """Приводит типы, которые json.dumps не умеет сериализовать напрямую, к
    JSON-совместимым: Decimal (так psycopg2 отдаёт NUMERIC-колонки в
    Postgres) -> число с плавающей точкой, date/datetime -> строка ISO
    ("YYYY-MM-DD" для дат, "YYYY-MM-DD HH:MM:SS[.ffffff]" для timestamp'ов) —
    именно эти форматы разбирает импорт в Mac-приложении
    (Business/DataImport.swift)."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return str(value)
    return str(value)


@bp.route("/export.json")
@roles_required("admin")
def export_json():
    """Полная выгрузка всех данных приложения в один JSON-файл — для
    переноса в другое хранилище (например, в локальную копию Mac-приложения,
    см. AGITMac/README.md -> «Перенос данных с сайта»). Отдаёт снимок ВСЕХ
    таблиц целиком (без фильтров и постраничности — на объёмах данных этого
    приложения это не проблема); поля выбраны по одному явно (не SELECT *),
    чтобы формат не менялся незаметно при будущих миграциях схемы, которые
    добавляют колонки, не нужные для переноса (opening_balance_qty,
    tool_assembly, act_number, служебные created_by и т.п. — сознательно не
    включены, они либо не имеют смысла вне этого сайта, либо не перенесены в
    Mac-приложение, см. AGITMac/README.md)."""
    data = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "parts": db.query_all(
            "SELECT id, part_name, part_number, is_serialized, min_stock_qty, category, tool_size, "
            "specification, unit_weight_kg, standard_cost_cny, exchange_rate, customs_duty_percent, "
            "unit_transfer_price_rub, created_at FROM parts ORDER BY id"
        ),
        "tools": db.query_all(
            "SELECT id, serial_number, tool_size, commissioned_date, cost_rub, created_at "
            "FROM tools ORDER BY id"
        ),
        "receipts": db.query_all(
            "SELECT id, part_id, receipt_date, order_ref, date_mfg, quantity, remaining_quantity, "
            "exchange_rate, total_cost_cny, transfer_price_rub, weight_kg, note, created_at "
            "FROM receipts ORDER BY id"
        ),
        "units": db.query_all(
            "SELECT id, part_id, serial_number, date_mfg, status, installed_on_tool_id, circulation_hours, "
            "service_count, od_mm, id_mm, remarks, paired_with_unit_id, receipt_id, created_at "
            "FROM units ORDER BY id"
        ),
        "service_jobs": db.query_all(
            "SELECT id, job_type, job_date, tool_id, title, work_order_number, performed_by, service_center, "
            "service_center_cost, labor_cost, other_cost, note, created_at FROM service_jobs ORDER BY id"
        ),
        "write_offs": db.query_all(
            "SELECT id, part_id, unit_id, receipt_id, quantity, write_off_date, reason, job_id, note, created_at "
            "FROM write_offs ORDER BY id"
        ),
        "tool_usage_logs": db.query_all(
            "SELECT id, tool_id, log_date, hours_added, note, created_at FROM tool_usage_logs ORDER BY id"
        ),
        "customers": db.query_all(
            "SELECT id, name, contract_number, note, created_at FROM customers ORDER BY id"
        ),
        "customer_rates": db.query_all(
            "SELECT id, customer_id, tool_size, work_rate, work_rate_unit, standby_rate_rub_per_day "
            "FROM customer_rates ORDER BY id"
        ),
        "tool_revenue": db.query_all(
            "SELECT id, tool_id, revenue_date, amount, currency, note, customer_id, well_number, work_qty, "
            "work_unit, standby_days, work_rate, standby_rate_rub_per_day, usage_hours, usage_log_id, created_at "
            "FROM tool_revenue ORDER BY id"
        ),
        "pairings": db.query_all(
            "SELECT id, rotor_unit_id, stator_unit_id, gap_mm, status, created_at FROM pairings ORDER BY id"
        ),
        "unit_repairs": db.query_all(
            "SELECT id, unit_id, job_id, repair_date, cost_rub, note, created_at FROM unit_repairs ORDER BY id"
        ),
    }
    body = json.dumps(data, default=_json_default, ensure_ascii=False)
    return Response(
        body.encode("utf-8"),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=agit_export.json"},
    )
