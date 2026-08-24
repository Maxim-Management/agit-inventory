"""Простая аутентификация на сессиях Flask (без внешних библиотек).
Роли: admin (полный доступ), engineer (может вносить поступления/списания/
наработку/пары), viewer (только просмотр)."""
import functools

from flask import Blueprint, render_template, request, redirect, url_for, session, g, flash
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

bp = Blueprint("auth", __name__)

ROLE_LABELS = {
    "admin": "Администратор",
    "engineer": "Инженер",
    "viewer": "Наблюдатель",
}


def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = db.query_one(
            "SELECT id, email, full_name, role, is_active FROM users WHERE id = %s",
            [user_id],
        )
        if g.user and not g.user.get("is_active", True):
            g.user = None
            session.clear()


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("auth.login", next=request.path))
            if g.user["role"] not in roles:
                flash("Недостаточно прав для этого действия.", "error")
                return redirect(url_for("dashboard.index"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def can_edit():
    """Инженер и администратор могут вносить операции, наблюдатель — нет."""
    return g.user is not None and g.user["role"] in ("admin", "engineer")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        error = None
        user = db.query_one("SELECT * FROM users WHERE email = %s", [email])
        if user is None or not check_password_hash(user["password_hash"], password):
            error = "Неверный email или пароль."
        elif not user.get("is_active", True):
            error = "Учётная запись отключена. Обратитесь к администратору."

        if error is None:
            session.clear()
            session["user_id"] = user["id"]
            next_url = request.args.get("next") or url_for("dashboard.index")
            return redirect(next_url)
        flash(error, "error")

    return render_template("auth/login.html")


@bp.route("/setup", methods=("GET", "POST"))
def setup():
    """Разовая настройка при первом запуске: если в базе ещё нет ни одного
    пользователя — позволяет создать первого администратора прямо через
    браузер, без запуска scripts/create_admin.py из терминала. Как только
    хотя бы один пользователь создан (через эту страницу или иначе),
    страница больше никого не пускает — только логин."""
    existing = db.query_one("SELECT COUNT(*) AS c FROM users")
    if existing and existing["c"] > 0:
        flash("Настройка уже выполнена — администратор существует. Войдите обычным способом.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        error = None
        if not email or "@" not in email:
            error = "Укажите корректный email."
        elif len(password) < 8:
            error = "Пароль должен быть не короче 8 символов."
        elif password != password2:
            error = "Пароли не совпадают."

        if error is None:
            user_id = db.execute_returning_id(
                """INSERT INTO users (email, password_hash, full_name, role, is_active)
                   VALUES (%s,%s,%s,'admin',%s) RETURNING id""",
                [email, generate_password_hash(password), full_name, True if db.IS_POSTGRES else 1],
            )
            session.clear()
            session["user_id"] = user_id
            flash("Администратор создан. Добро пожаловать!", "ok")
            return redirect(url_for("dashboard.index"))
        flash(error, "error")

    return render_template("auth/setup.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/account/password", methods=("GET", "POST"))
def change_password():
    if g.user is None:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        user = db.query_one("SELECT * FROM users WHERE id = %s", [g.user["id"]])
        if not check_password_hash(user["password_hash"], current_password):
            flash("Текущий пароль указан неверно.", "error")
        elif len(new_password) < 8:
            flash("Новый пароль должен быть не короче 8 символов.", "error")
        else:
            db.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                [generate_password_hash(new_password), g.user["id"]],
            )
            flash("Пароль изменён.", "ok")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/change_password.html")
