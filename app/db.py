"""
Тонкий слой доступа к БД, работающий поверх SQLite (локальная разработка /
демо-режим) или PostgreSQL (продакшн, напр. Supabase) — выбор делается через
переменную окружения DATABASE_URL.

Все запросы в коде пишутся в стиле PostgreSQL (плейсхолдеры %s). Для SQLite
они автоматически транслируются в '?'. Это позволяет использовать один и тот
же код приложения для локального тестирования (SQLite, есть "из коробки" в
Python) и для продакшн-развёртывания на Vercel + Supabase (PostgreSQL).
"""
import os
import re
import sqlite3
import threading
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")

SQLITE_PATH = os.environ.get("SQLITE_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "agit.db"))

_PLACEHOLDER_RE = re.compile(r"%s")


def _to_sqlite(query: str) -> str:
    return _PLACEHOLDER_RE.sub("?", query)


class SqliteCursorWrapper:
    """Обёртка над sqlite3.Cursor, чтобы она вела себя как psycopg2-курсор
    в части dict-подобных строк (через row_factory) и .fetchone()/.fetchall()."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        q = _to_sqlite(query)
        # SQLite не понимает ON CONFLICT ... DO UPDATE SET x = EXCLUDED.x синтаксис
        # ровно как Postgres в сложных случаях, но базовый ON CONFLICT поддерживает.
        self._cursor.execute(q, params or [])
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(r) for r in self._cursor.fetchall()]

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid


class SqliteConnWrapper:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return SqliteCursorWrapper(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def executescript(self, sql):
        self._conn.executescript(sql)


def _get_raw_connection():
    if IS_POSTGRES:
        import time

        import psycopg2
        import psycopg2.extras

        # До 3 попыток с паузой — Supabase иногда обрывает соединение или
        # отвечает не сразу (например, бесплатный проект "просыпается" после
        # простоя), и повторная попытка через секунду обычно уже проходит.
        last_error = None
        for attempt in range(3):
            try:
                return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
            except psycopg2.OperationalError as e:
                last_error = e
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        raise last_error
    else:
        if os.environ.get("VERCEL"):
            # Мы выполняемся как serverless-функция на Vercel, но DATABASE_URL
            # не задан (или задан не в этом окружении деплоя) — если бы мы
            # молча откатились на SQLite, приложение читало бы и писало бы в
            # локальный файл data/agit.db, случайно попавший в репозиторий
            # (например, при загрузке файлов через веб-интерфейс GitHub,
            # который не учитывает .gitignore) — включая демо-администратора
            # оттуда. Это опасная и очень запутывающая ситуация, поэтому
            # лучше явно упасть с понятной ошибкой, чем незаметно работать не
            # с той базой.
            raise RuntimeError(
                "DATABASE_URL не задан (или задан не для этого окружения деплоя) "
                "в переменных окружения Vercel — см. Project Settings -> "
                "Environment Variables, затем сделайте Redeploy. Без него "
                "сервис на Vercel не должен обращаться к локальному "
                "SQLite-файлу — это может оказаться демо-база из репозитория."
            )
        os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
        conn = sqlite3.connect(SQLITE_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return SqliteConnWrapper(conn)


_local = threading.local()


def _set_autocommit(conn):
    # Автокоммит на каждый отдельный запрос нужен только для PostgreSQL —
    # там это даёт устойчивость к обрыву соединения пулером посреди
    # импорта (см. docstring bulk_session). Для локальной SQLite это лишнее
    # и вредное: каждый autocommit — это отдельный fsync на диск, а их за
    # импорт сотни, отчего импорт вместо секунд может идти минутами.
    # SQLite — один локальный файл, соединение с ним не "обрывается", как
    # с сетевым пулером, поэтому там по-прежнему используется одна большая
    # транзакция с одним commit() в конце (см. bulk_session).
    if IS_POSTGRES:
        conn.autocommit = True


def _is_connection_error(e):
    if not IS_POSTGRES:
        return False
    import psycopg2

    return isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError))


def _reconnect_bulk_session():
    old = getattr(_local, "conn", None)
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    conn = _get_raw_connection()
    _set_autocommit(conn)
    _local.conn = conn
    return conn


@contextmanager
def bulk_session():
    """Открывает ОДНО подключение к БД и переиспользует его для всех запросов
    внутри блока `with db.bulk_session():`, вместо того чтобы открывать новое
    соединение на каждый отдельный query_all/query_one/execute/
    execute_returning_id (как происходит по умолчанию — это нормально и
    безопасно для веб-запросов, где на один запрос приходится немного
    обращений к БД).

    Нужно для скриптов вроде import_excel.py, которые выполняют сотни
    запросов подряд: открытие/закрытие отдельного соединения на каждый из
    них — это сотни TCP/TLS-рукопожатий за секунды, что для пулера Supabase
    (Transaction pooler) на бесплатном тарифе может закончиться обрывом
    соединения ("server closed the connection unexpectedly") из-за слишком
    частого создания новых подключений.

    Каждый отдельный запрос коммитится сразу (autocommit) — если соединение
    всё же оборвётся посреди импорта (нестабильная сеть, "просыпающийся"
    бесплатный проект Supabase и т.п.), уже выполненные запросы не теряются
    и не откатываются, а query_all/query_one/execute/execute_returning_id
    автоматически переподключаются и повторяют именно тот запрос, на котором
    произошёл обрыв — до 3 попыток.

    Для SQLite (локальная разработка) автокоммит не включается — вместо
    этого используется одна транзакция на весь блок с explicit commit() в
    конце (быстрее и вполне безопасно для локального файла)."""
    conn = _get_raw_connection()
    _set_autocommit(conn)
    _local.conn = conn
    try:
        yield conn
        if not IS_POSTGRES:
            conn.commit()
    except Exception:
        if not IS_POSTGRES:
            conn.rollback()
        raise
    finally:
        _local.conn = None
        try:
            conn.close()
        except Exception:
            pass


@contextmanager
def get_conn():
    active = getattr(_local, "conn", None)
    if active is not None:
        # Внутри bulk_session() — используем то же самое соединение
        # (autocommit уже включён на уровне bulk_session).
        yield active
        return
    conn = _get_raw_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _run(query, params, fetch):
    """Выполняет запрос и возвращает fetch(cursor). Вне bulk_session — как
    раньше, отдельное подключение на вызов. Внутри bulk_session — на общем
    долгоживущем соединении, с автоматическим переподключением и повтором
    запроса (до 3 попыток), если соединение оборвалось сервером/пулером."""
    active = getattr(_local, "conn", None)
    if active is None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(query, params or [])
            return fetch(cur)

    last_error = None
    for attempt in range(3):
        try:
            cur = active.cursor()
            cur.execute(query, params or [])
            return fetch(cur)
        except Exception as e:
            last_error = e
            if not _is_connection_error(e):
                raise
            active = _reconnect_bulk_session()
    raise last_error


def query_all(query, params=None):
    return _run(query, params, lambda cur: cur.fetchall())


def query_one(query, params=None):
    return _run(query, params, lambda cur: cur.fetchone())


def execute(query, params=None):
    """INSERT/UPDATE/DELETE без возврата значения."""
    return _run(query, params, lambda cur: cur.rowcount)


def execute_returning_id(query, params=None):
    """Для INSERT ... RETURNING id — работает и в Postgres, и в SQLite >= 3.35."""
    def fetch(cur):
        row = cur.fetchone()
        return row["id"] if row else None
    return _run(query, params, fetch)
