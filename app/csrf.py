"""Минимальная защита от CSRF (без внешних зависимостей): токен на сессию,
скрытое поле в формах, проверка на все небезопасные методы."""
import secrets

from flask import session, request, abort


def get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def init_app(app):
    app.jinja_env.globals["csrf_token"] = get_csrf_token

    @app.before_request
    def _check_csrf():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            # логин ещё не имеет сессии с токеном на первом заходе — но т.к.
            # get_csrf_token создаёт токен при любом GET (форма логина рендерится
            # через GET перед этим), к моменту POST токен уже есть в сессии.
            sent = request.form.get("csrf_token", "")
            expected = session.get("_csrf_token", "")
            if not expected or not secrets.compare_digest(sent, expected):
                abort(400, description="Некорректный CSRF-токен. Обновите страницу и повторите попытку.")
