"""Справочник заказчиков — используется при внесении выручки по инструменту
(app/tools.py: log_tool_revenue). У каждого заказчика — отдельная ставка для
КАЖДОГО типоразмера инструмента (стоимость работы и дежурства может
отличаться в зависимости от размера, см. TOOL_SIZES ниже). При выборе
заказчика на форме выручки ставка для типоразмера ИМЕННО этого инструмента
подтягивается автоматически и "замораживается" (сохраняется снимком) на
самой записи выручки — более позднее изменение ставки в карточке заказчика
не искажает задним числом уже внесённую выручку."""
from . import db

# Типоразмеры, для которых заводятся отдельные ставки — те же три, что
# используются во всём приложении для наименования инструмента (см.
# _TOOL_NAME_RULES в app/tools.py). Порядок важен для отображения форм.
TOOL_SIZES = ["4 3/4", "6 3/4", "8"]

WORK_RATE_UNIT_LABELS = {"hour": "ч", "day": "сут"}


def list_customers(q=None):
    sql = "SELECT * FROM customers WHERE 1=1"
    params = []
    if q:
        sql += " AND (name LIKE %s OR contract_number LIKE %s)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY name"
    return db.query_all(sql, params)


def get_customer(customer_id):
    return db.query_one("SELECT * FROM customers WHERE id = %s", [customer_id])


def create_customer(name, contract_number, note, created_by):
    return db.execute_returning_id(
        "INSERT INTO customers (name, contract_number, note, created_by) VALUES (%s,%s,%s,%s) RETURNING id",
        [name, contract_number or "", note or "", created_by],
    )


def update_customer(customer_id, name, contract_number, note):
    db.execute(
        "UPDATE customers SET name=%s, contract_number=%s, note=%s WHERE id=%s",
        [name, contract_number or "", note or "", customer_id],
    )


def customer_revenue_total(customer_id):
    row = db.query_one("SELECT COALESCE(SUM(amount),0) AS s FROM tool_revenue WHERE customer_id = %s", [customer_id])
    return float(row["s"] or 0)


# ---------------------------------------------------------------------------
# Ставки по типоразмеру (customer_rates)
# ---------------------------------------------------------------------------

def get_customer_rates_map(customer_id):
    """Ставки заказчика по всем TOOL_SIZES, {typoразмер: {work_rate,
    work_rate_unit, standby_rate_rub_per_day}} — размеры, для которых ставка
    ещё не заводилась, отдаются с нулями/часом по умолчанию (чтобы форма
    редактирования всегда показывала все три размера)."""
    rows = db.query_all("SELECT * FROM customer_rates WHERE customer_id = %s", [customer_id])
    by_size = {r["tool_size"]: r for r in rows}
    result = {}
    for size in TOOL_SIZES:
        r = by_size.get(size)
        if r:
            result[size] = {
                "work_rate": float(r["work_rate"] or 0),
                "work_rate_unit": r["work_rate_unit"] or "hour",
                "standby_rate_rub_per_day": float(r["standby_rate_rub_per_day"] or 0),
            }
        else:
            result[size] = {"work_rate": 0.0, "work_rate_unit": "hour", "standby_rate_rub_per_day": 0.0}
    return result


def set_customer_rate(customer_id, tool_size, work_rate, work_rate_unit, standby_rate_rub_per_day):
    work_rate_unit = work_rate_unit if work_rate_unit in ("hour", "day") else "hour"
    updated = db.execute(
        "UPDATE customer_rates SET work_rate=%s, work_rate_unit=%s, standby_rate_rub_per_day=%s "
        "WHERE customer_id=%s AND tool_size=%s",
        [work_rate or 0, work_rate_unit, standby_rate_rub_per_day or 0, customer_id, tool_size],
    )
    if not updated:
        db.execute(
            "INSERT INTO customer_rates (customer_id, tool_size, work_rate, work_rate_unit, standby_rate_rub_per_day) "
            "VALUES (%s,%s,%s,%s,%s)",
            [customer_id, tool_size, work_rate or 0, work_rate_unit, standby_rate_rub_per_day or 0],
        )


def _matches_tool_size(needle, actual_tool_size):
    """Та же логика нестрогого сравнения, что и в tool_display_name()
    (app/tools.py) — типоразмер в карточках может быть записан по-разному
    (с кавычками/без, с пробелом/без), сравниваем по вхождению цифр
    размера в строку."""
    return needle in (actual_tool_size or "")


def get_rate_for_tool(customer_id, actual_tool_size):
    """Ставка заказчика для типоразмера КОНКРЕТНОГО инструмента (сравнение
    нестрогое — см. _matches_tool_size). None, если для этого размера у
    заказчика ставка не задана (все нули) — вызывающий код должен либо
    попросить задать ставку, либо не позволить внести такую выручку."""
    rates = get_customer_rates_map(customer_id)
    for size in TOOL_SIZES:
        if _matches_tool_size(size, actual_tool_size):
            rate = rates[size]
            if rate["work_rate"] or rate["standby_rate_rub_per_day"]:
                return {"tool_size": size, **rate}
            return None
    return None
