from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from werkzeug.security import generate_password_hash
import secrets

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
