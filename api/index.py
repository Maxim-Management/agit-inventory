"""Точка входа для развёртывания на Vercel (Python-функция).
Vercel собирает этот файл и проксирует все запросы в переменную `app`
(Flask-приложение реализует стандартный WSGI-интерфейс)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import create_app  # noqa: E402

app = create_app()
