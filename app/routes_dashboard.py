from datetime import date, timedelta

from flask import Blueprint, render_template, g, redirect, url_for

from . import db
from .auth import login_required
from .stock import stock_map, total_stock_value

bp = Blueprint("dashboard", __name__)


@bp.route("/dashboard")
@login_required
def index():
    total_parts = db.query_one("SELECT COUNT(*) AS c FROM parts")["c"]
    total_in_stock = db.query_one("SELECT COUNT(*) AS c FROM units WHERE status = 'in_stock'")["c"]
    total_installed = db.query_one("SELECT COUNT(*) AS c FROM units WHERE status = 'installed'")["c"]
    total_written_off = db.query_one("SELECT COUNT(*) AS c FROM units WHERE status = 'written_off'")["c"]
    stock_value_rub = total_stock_value()

    stock = stock_map()
    parts = db.query_all("SELECT id, part_name, part_number, tool_size, min_stock_qty FROM parts")
    low_stock = sorted(
        (
            {**p, "in_stock": stock.get(p["id"], 0)}
            for p in parts
            if stock.get(p["id"], 0) < p["min_stock_qty"]
        ),
        key=lambda p: p["min_stock_qty"] - p["in_stock"],
        reverse=True,
    )[:10]

    recent_writeoffs = db.query_all(
        """
        SELECT w.id, w.write_off_date, w.reason, w.quantity, u.serial_number, p.part_name
        FROM write_offs w
        JOIN parts p ON p.id = w.part_id
        LEFT JOIN units u ON u.id = w.unit_id
        ORDER BY w.write_off_date DESC, w.id DESC
        LIMIT 8
        """
    )

    recent_receipts = db.query_all(
        """
        SELECT r.id, r.receipt_date, r.quantity, r.order_ref, p.part_name
        FROM receipts r
        JOIN parts p ON p.id = r.part_id
        ORDER BY r.receipt_date DESC, r.id DESC
        LIMIT 8
        """
    )

    thirty_days_ago = (date.today() - timedelta(days=30)).isoformat()
    writeoffs_30d = db.query_one(
        "SELECT COUNT(*) AS c FROM write_offs WHERE write_off_date >= %s", [thirty_days_ago]
    )["c"]

    return render_template(
        "dashboard.html",
        total_parts=total_parts,
        total_in_stock=total_in_stock,
        total_installed=total_installed,
        total_written_off=total_written_off,
        stock_value_rub=stock_value_rub,
        low_stock=low_stock,
        recent_writeoffs=recent_writeoffs,
        recent_receipts=recent_receipts,
        writeoffs_30d=writeoffs_30d,
    )
