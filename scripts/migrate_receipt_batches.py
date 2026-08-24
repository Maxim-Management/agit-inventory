"""
Разовый скрипт миграции данных на партийную модель поступлений (см. миграцию
0008_receipt_batches.sql и app/stock.py). Нужен один раз — сразу после
применения миграции 0008 к базе (локальной или продакшн Supabase) — чтобы
проставить остатки по партиям (receipts.remaining_quantity) и обратные
ссылки серийных единиц на партию (units.receipt_id) для ДАННЫХ, УЖЕ
СУЩЕСТВОВАВШИХ ДО перехода на партийную модель. Новые поступления, вносимые
через само приложение после этой миграции, уже создаются корректно (см.
app/routes_receipts.py) и в пересчёте не нуждаются.

ВАЖНО: запускайте scripts/dedupe_receipts.py (сначала в режиме сухого
прогона, затем — если нашлись дубликаты — с флагом --apply) ДО этого
скрипта, иначе задвоенные исторические записи о поступлении получат каждая
свой (задвоенный) остаток.

Что делает:
  1. Серийные детали: для каждой единицы (units), у которой ещё нет
     receipt_id, но связанная с ней ЛЕГАСИ-запись receipts.unit_id указывает
     именно на неё — проставляет units.receipt_id = receipts.id (обратная
     связь), а remaining_quantity этой партии выставляет в 1, если единица
     сейчас на складе (status='in_stock'), и в 0, если она уже установлена,
     в паре или списана (её экземпляр из партии больше не в остатке).
     Партии, у которых нет ни одной привязанной единицы (исторические
     записи без unit_id) остаются с remaining_quantity=0 — по какой именно
     партии числится текущий остаток такой детали, восстановить нельзя
     (в карточке детали это отражается как "не включено в оценку остатка").

  2. Несерийные расходники (масло, уплотнения и т.п.): remaining_quantity
     их партий выставляется так, чтобы СУММА остатков по партиям детали
     совпадала с фактическим текущим остатком по формуле app/stock.py
     (opening_balance_qty + поступления после даты среза − списания после
     даты среза) — по правилу FIFO "наоборот": считается, что расходуются
     сначала самые старые партии, поэтому остаток заполняется начиная с
     САМЫХ НОВЫХ партий и назад, пока не наберётся нужное количество.
     Если распределить весь остаток по партиям не получилось (например,
     часть остатка относится к "остатку на начало", введённому без
     привязки к конкретному поступлению) — остаётся неучтённый хвост,
     который в карточке детали помечается как "не включено в оценку
     остатка" (см. app/templates/parts/detail.html).

Скрипт идемпотентен: повторный запуск даёт тот же результат (пересчитывает
remaining_quantity заново по текущим статусам единиц / текущему остатку, не
накапливая ошибку при повторных запусках).

Запуск (локально, SQLite из .env):
  python scripts/migrate_receipt_batches.py

Запуск против продакшн-базы на Supabase:
  DATABASE_URL="postgresql://...supabase..." python scripts/migrate_receipt_batches.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from app import db  # noqa: E402
from app.stock import stock_map  # noqa: E402


def migrate_serialized():
    print("Серийные детали: восстанавливаю units.receipt_id из легаси receipts.unit_id...")
    legacy_links = db.query_all(
        "SELECT id AS receipt_id, unit_id, quantity FROM receipts WHERE unit_id IS NOT NULL"
    )
    linked = 0
    for r in legacy_links:
        updated = db.execute(
            "UPDATE units SET receipt_id = %s WHERE id = %s AND receipt_id IS NULL",
            [r["receipt_id"], r["unit_id"]],
        )
        linked += updated
    print(f"  Восстановлено обратных ссылок (units.receipt_id): {linked}")

    print("Серийные детали: пересчитываю remaining_quantity партий по статусу привязанных единиц...")
    all_receipts = db.query_all(
        """SELECT r.id, r.quantity, p.is_serialized
           FROM receipts r JOIN parts p ON p.id = r.part_id
           WHERE p.is_serialized = %s""",
        [True],
    )
    updated_count = 0
    for r in all_receipts:
        units = db.query_all("SELECT status FROM units WHERE receipt_id = %s", [r["id"]])
        if not units:
            # Историческая партия без привязанной единицы — остаток по ней
            # восстановить нельзя, оставляем 0 (не участвует в оценке
            # стоимости остатка, см. предупреждение в карточке детали).
            remaining = 0
        else:
            remaining = sum(1 for u in units if u["status"] == "in_stock")
        db.execute("UPDATE receipts SET remaining_quantity = %s WHERE id = %s", [remaining, r["id"]])
        updated_count += 1
    print(f"  Пересчитано партий: {updated_count}")


def migrate_bulk():
    print("Несерийные расходники: распределяю фактический остаток по партиям (FIFO, от новых к старым)...")
    stock = stock_map()
    parts = db.query_all("SELECT id, part_name FROM parts WHERE is_serialized = %s", [False])
    total_unaccounted = 0.0
    for p in parts:
        target = float(stock.get(p["id"], 0) or 0)
        batches = db.query_all(
            "SELECT id, quantity FROM receipts WHERE part_id = %s ORDER BY receipt_date DESC, id DESC",
            [p["id"]],
        )
        remaining_target = max(target, 0.0)
        for b in batches:
            qty = float(b["quantity"] or 0)
            assign = min(qty, remaining_target)
            db.execute("UPDATE receipts SET remaining_quantity = %s WHERE id = %s", [assign, b["id"]])
            remaining_target -= assign
        if remaining_target > 0.0001:
            total_unaccounted += remaining_target
            print(
                f"  {p['part_name']}: остаток {target:g}, из партий получилось распределить только "
                f"{target - remaining_target:g} — {remaining_target:g} не привязано ни к одной партии "
                f"(вероятно, часть 'остатка на начало', введённая без поступления)."
            )
    print(f"  Готово. Неучтённого остатка по всем расходникам суммарно: {total_unaccounted:g}")


def main():
    migrate_serialized()
    migrate_bulk()
    print("\nМиграция остатков по партиям завершена.")


if __name__ == "__main__":
    main()
