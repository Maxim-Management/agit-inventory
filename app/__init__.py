import os

from flask import Flask, g, redirect, url_for

from . import auth


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-insecure-change-me"),
    )
    if test_config:
        app.config.update(test_config)

    from . import csrf
    csrf.init_app(app)

    app.before_request(auth.load_logged_in_user)

    @app.context_processor
    def inject_globals():
        from . import auth as auth_mod
        user = g.get("user")
        return {
            "current_user": user,
            "can_edit": auth_mod.can_edit(),
            "is_admin": user is not None and user["role"] == "admin",
            "role_labels": auth_mod.ROLE_LABELS,
        }

    app.register_blueprint(auth.bp)

    from . import routes_dashboard, routes_parts, routes_units, routes_receipts
    from . import routes_writeoffs, routes_pairing, routes_analytics, routes_forecast, routes_admin, routes_jobs
    from . import routes_tools, routes_customers

    app.register_blueprint(routes_dashboard.bp)
    app.register_blueprint(routes_parts.bp)
    app.register_blueprint(routes_units.bp)
    app.register_blueprint(routes_receipts.bp)
    app.register_blueprint(routes_writeoffs.bp)
    app.register_blueprint(routes_pairing.bp)
    app.register_blueprint(routes_analytics.bp)
    app.register_blueprint(routes_forecast.bp)
    app.register_blueprint(routes_admin.bp)
    app.register_blueprint(routes_jobs.bp)
    app.register_blueprint(routes_tools.bp)
    app.register_blueprint(routes_customers.bp)

    @app.route("/")
    def root():
        return redirect(url_for("dashboard.index"))

    @app.template_filter("num")
    def fmt_num(value, digits=2):
        if value is None:
            return "—"
        try:
            f = float(value)
        except (TypeError, ValueError):
            return value
        if f == int(f):
            return str(int(f))
        return f"{f:.{digits}f}"

    return app
