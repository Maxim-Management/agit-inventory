"""Создаёт первого администратора. Запуск:
  python scripts/create_admin.py you@company.com "Имя Фамилия"
Пароль будет сгенерирован и выведен в консоль (либо задайте его переменной
окружения ADMIN_PASSWORD)."""
import os
import sys
import secrets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from werkzeug.security import generate_password_hash  # noqa: E402
from app import db  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("Использование: python scripts/create_admin.py email@company.com [\"Имя\"]")
        sys.exit(1)
    email = sys.argv[1].strip().lower()
    full_name = sys.argv[2] if len(sys.argv) > 2 else "Администратор"
    password = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(9)

    existing = db.query_one("SELECT id FROM users WHERE email = %s", [email])
    if existing:
        db.execute(
            "UPDATE users SET password_hash = %s, role = 'admin', is_active = %s WHERE email = %s",
            [generate_password_hash(password), True if db.IS_POSTGRES else 1, email],
        )
        print(f"Пользователь {email} уже существовал — обновлён до роли admin, пароль сброшен.")
    else:
        db.execute(
            "INSERT INTO users (email, password_hash, full_name, role) VALUES (%s,%s,%s,'admin')",
            [email, generate_password_hash(password), full_name],
        )
        print(f"Администратор {email} создан.")

    print(f"Пароль: {password}")
    print("Сохраните пароль — он не хранится в открытом виде и не будет показан повторно.")


if __name__ == "__main__":
    main()
