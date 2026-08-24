from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from . import db
from .auth import login_required, roles_required
from .matching import suggest_pairs, evaluate_pair, GAP_MIN, GAP_MAX

bp = Blueprint("pairing", __name__, url_prefix="/pairing")


@bp.route("/")
@login_required
def index():
    tool_size = request.args.get("tool_size", "").strip()
    gap_min = float(request.args.get("gap_min", GAP_MIN))
    gap_max = float(request.args.get("gap_max", GAP_MAX))

    tool_sizes = [r["tool_size"] for r in db.query_all(
        "SELECT DISTINCT tool_size FROM parts WHERE tool_size != '' ORDER BY tool_size")]

    rotor_sql = """
        SELECT u.id, u.serial_number, u.od_mm, u.remarks, p.part_name, p.tool_size
        FROM units u JOIN parts p ON p.id = u.part_id
        WHERE p.category = 'rotor' AND u.status = 'in_stock' AND u.od_mm IS NOT NULL
    """
    stator_sql = """
        SELECT u.id, u.serial_number, u.id_mm, u.remarks, p.part_name, p.tool_size
        FROM units u JOIN parts p ON p.id = u.part_id
        WHERE p.category = 'stator' AND u.status = 'in_stock' AND u.id_mm IS NOT NULL
    """
    params = []
    if tool_size:
        rotor_sql += " AND p.tool_size = %s"
        stator_sql += " AND p.tool_size = %s"
        params = [tool_size]

    rotors = db.query_all(rotor_sql + " ORDER BY u.od_mm", params)
    stators = db.query_all(stator_sql + " ORDER BY u.id_mm", params)

    suggestions = suggest_pairs(rotors, stators, gap_min=gap_min, gap_max=gap_max)

    matched_rotor_ids = {s["rotor"]["id"] for s in suggestions}
    matched_stator_ids = {s["stator"]["id"] for s in suggestions}
    unmatched_rotors = [r for r in rotors if r["id"] not in matched_rotor_ids]
    unmatched_stators = [s for s in stators if s["id"] not in matched_stator_ids]

    history = db.query_all(
        """SELECT pr.*, ur.serial_number AS rotor_sn, us.serial_number AS stator_sn
           FROM pairings pr
           JOIN units ur ON ur.id = pr.rotor_unit_id
           JOIN units us ON us.id = pr.stator_unit_id
           ORDER BY pr.created_at DESC LIMIT 20"""
    )

    return render_template(
        "pairing/index.html", tool_sizes=tool_sizes, tool_size=tool_size,
        gap_min=gap_min, gap_max=gap_max, rotors=rotors, stators=stators,
        suggestions=suggestions, unmatched_rotors=unmatched_rotors,
        unmatched_stators=unmatched_stators, history=history,
    )


@bp.route("/confirm", methods=("POST",))
@roles_required("admin", "engineer")
def confirm():
    rotor_id = request.form["rotor_unit_id"]
    stator_id = request.form["stator_unit_id"]
    rotor = db.query_one("SELECT * FROM units WHERE id = %s", [rotor_id])
    stator = db.query_one("SELECT * FROM units WHERE id = %s", [stator_id])
    ev = evaluate_pair(rotor["od_mm"] if rotor else None, stator["id_mm"] if stator else None)
    if not ev["valid"]:
        flash("Зазор вне допустимого диапазона — пара не подтверждена.", "error")
        return redirect(url_for("pairing.index"))

    db.execute(
        """INSERT INTO pairings (rotor_unit_id, stator_unit_id, gap_mm, status, created_by)
           VALUES (%s,%s,%s,'confirmed',%s)""",
        [rotor_id, stator_id, ev["gap_mm"], g.user["id"]],
    )
    db.execute("UPDATE units SET status = 'paired', paired_with_unit_id = %s WHERE id = %s", [stator_id, rotor_id])
    db.execute("UPDATE units SET status = 'paired', paired_with_unit_id = %s WHERE id = %s", [rotor_id, stator_id])
    flash(f"Пара подтверждена, зазор {ev['gap_mm']} мм.", "ok")
    return redirect(url_for("pairing.index"))
