"""
Разовый скрипт очистки: находит и (по флагу --apply) удаляет точные
дубликаты записей о поступлении (receipts) — например, если один и тот же
приход был случайно внесён дважды (двойной клик по «Сохранить», повторный
запуск импорта и т.п.).

Дубликатом считаются строки receipts с ПОЛНОСТЬЮ совпадающими:
  part_id, unit_id, quantity, receipt_date, order_ref,
  date_mfg, exchange_rate, total_cost_cny, transfer_price_rub, note
(id и created_at из сравнения намеренно исключены — это единственное, чем
дубликаты отличаются друг от друга).

Обратите внимание: для СЕРИЙНЫХ деталей, ввезённых партией из нескольких
серийных номеров, каждая физическая единица исторически (до перехода на
партийную модель, см. миграцию 0008 и app/routes_receipts.py) могла иметь
СВОЮ строку receipts — но с РАЗНЫМ unit_id, поэтому такие строки дубликатами
не считаются и не удаляются. Под удаление подпадают только записи, у
которых unit_id (или его отсутствие — NULL) тоже совпадает.

По умолчанию скрипт работает в режиме "сухого прогона" (dry-run): только
печатает найденные группы дубликатов и что было бы удалено, ничего не
меняя в БД. Чтобы реально удалить лишние строки, запустите с флагом --apply.

Из каждой группы дубликатов сохраняется строка с наименьшим id, остальные
удаляются. Если на удаляемую строку уже есть ссылки (units.receipt_id или
write_offs.receipt_id), они переносятся на сохраняемую строку — стоимость
остатка/списаний по партии от этого не теряется.

ВАЖНО: запускайте этот скрипт ДО scripts/migrate_receipt_batches.py — иначе
уже перелинкованные remaining_quantity и units.receipt_id придётся
пересчитывать заново.

Запуск (сухой прогон — ничего не меняет):
  python scripts/dedupe_receipts.py

Запуск (реально удаляет найденные дубликаты):
  python scripts/dedupe_receipts.py --apply

Для работы с продакшн-базой на Supabase — так же, как и для других
разовых скриптов (import_excel.py и т.п.): задайте переменную окружения
DATABASE_URL перед запуском, например:
  DATABASE_URL="postgresql://...supabase..." python scripts/dedupe_receipts.py --apply
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from app import db  # noqa: E402

DEDUPE_FIELDS = [
    "part_id", "unit_id", "quantity", "receipt_date", "order_ref",
    "date_mfg", "exchange_rate",
    "total_cost_cny", "transfer_price_rub", "note",
]


def _norm(v):
    """Нормализует значение для сравнения — Decimal/float/int с одинаковой
    величиной должны считаться равными (полем сравнения занимается float())."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        # decimal.Decimal и подобные — приводим к float для сравнения
        return float(v)
    except (TypeError, ValueError):
        return v


def _dedupe_key(r):
    return tuple(_norm(r.get(f)) for f in DEDUPE_FIELDS)


def main():
    apply_changes = "--apply" in sys.argv

    rows = db.query_all("SELECT * FROM receipts ORDER BY id")
    groups = defaultdict(list)
    for r in rows:
        groups[_dedupe_key(r)].append(r)

    dup_groups = [g for g in groups.values() if len(g) > 1]

    if not dup_groups:
        print(f"Проверено записей о поступлении: {len(rows)}. Дубликатов не найдено.")
        return

    total_to_delete = 0
    print(f"Проверено записей о поступлении: {len(rows)}.")
    print(f"Найдено групп дубликатов: {len(dup_groups)}\n")

    for g in dup_groups:
        g_sorted = sorted(g, key=lambda r: r["id"])
        keep = g_sorted[0]
        remove = g_sorted[1:]
        total_to_delete += len(remove)
        print(
            f"  Деталь part_id={keep['part_id']}, заказ «{keep.get('order_ref') or '—'}», "
            f"кол-во {keep['quantity']}, дата {keep['receipt_date']}: "
            f"сохраняем id={keep['id']}, удаляем id={[r['id'] for r in remove]}"
        )
        if apply_changes:
            for r in remove:
                # Переносим ссылки на удаляемую строку на сохраняемую, чтобы
                # не потерять привязку остатка партии / списаний к партии.
                db.execute("UPDATE units SET receipt_id = %s WHERE receipt_id = %s", [keep["id"], r["id"]])
                db.execute("UPDATE write_offs SET receipt_id = %s WHERE receipt_id = %s", [keep["id"], r["id"]])
                db.execute("DELETE FROM receipts WHERE id = %s", [r["id"]])

    print(f"\nВсего лишних записей {'удалено' if apply_changes else 'найдено (не удалено — сухой прогон)'}: {total_to_delete}.")
    if not apply_changes:
        print("Ничего не изменено. Чтобы удалить дубликаты, запустите: python scripts/dedupe_receipts.py --apply")


if __name__ == "__main__":
    main()
