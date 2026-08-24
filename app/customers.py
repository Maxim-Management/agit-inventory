"""Справочник заказчиков — используется при внесении выручки по инструменту
(app/tools.py: log_tool_revenue). У каждого заказчика своя ставка за час
работы и за сутки ожидания/дежурства; при выборе заказчика на форме выручки
эти ставки подтягиваются автоматически и "замораживаются" (сохраняются
снимком) на самой записи выручки — более позднее изменение ставки в этой
карточке не искажает задним числом уже внесённую выручку."""
from . import db


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


def create_customer(name, contract_number, work_rate_rub_per_hour, standby_rate_rub_per_day, note, created_by):
    return db.execute_returning_id(
        """INSERT INTO customers (name, contract_number, work_rate_rub_per_hour,
                                   standby_rate_rub_per_day, note, created_by)
           VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
        [name, contract_number or "", work_rate_rub_per_hour or 0, standby_rate_rub_per_day or 0,
         note or "", created_by],
    )


def update_customer(customer_id, name, contract_number, work_rate_rub_per_hour, standby_rate_rub_per_day, note):
    db.execute(
        """UPDATE customers SET name=%s, contract_number=%s, work_rate_rub_per_hour=%s,
                                 standby_rate_rub_per_day=%s, note=%s WHERE id=%s""",
        [name, contract_number or "", work_rate_rub_per_hour or 0, standby_rate_rub_per_day or 0,
         note or "", customer_id],
    )


def customer_revenue_total(customer_id):
    row = db.query_one("SELECT COALESCE(SUM(amount),0) AS s FROM tool_revenue WHERE customer_id = %s", [customer_id])
    return float(row["s"] or 0)
