"""Создаёт таблицы БД. Использует schema_sqlite.sql для локальной SQLite
(если DATABASE_URL не задан) или schema_postgres.sql для PostgreSQL.

Запуск: python scripts/init_db.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from app import db  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def main():
    if db.IS_POSTGRES:
        schema_path = os.path.join(ROOT, "schema_postgres.sql")
        print(f"Обнаружен DATABASE_URL (PostgreSQL). Применяю {schema_path}...")
    else:
        schema_path = os.path.join(ROOT, "schema_sqlite.sql")
        print(f"DATABASE_URL не задан — используется локальная SQLite ({db.SQLITE_PATH}).")
        print(f"Применяю {schema_path}...")

    with open(schema_path, encoding="utf-8") as f:
        sql = f.read()

    with db.get_conn() as conn:
        cur = conn.cursor()
        if db.IS_POSTGRES:
            cur.execute(sql)
        else:
            # sqlite3 требует executescript для набора выражений через ';'
            conn.executescript(sql)

    print("Готово: таблицы созданы (или уже существовали).")


if __name__ == "__main__":
    main()
