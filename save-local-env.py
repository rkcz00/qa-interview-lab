"""Сохраняет локальные секреты из текущего PowerShell без вывода значений."""

import os
import re
import secrets
from pathlib import Path


REQUIRED_KEYS = ("DJANGO_SECRET_KEY", "POSTGRES_PASSWORD")


def save_local_env(root: Path) -> None:
    target = root / ".env"
    ignore_rules = (root / ".gitignore").read_text(encoding="utf-8-sig").splitlines()
    if not all(rule in ignore_rules for rule in (".env", ".env.*", "!.env.example")):
        raise SystemExit("BLOCKED: проверьте правила .env в .gitignore. Запись не выполнялась.")

    if target.exists():
        # Проверяем ключи непосредственно в файле, без значений родительского процесса.
        existing = {}
        for line in target.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator:
                raise SystemExit("BLOCKED: проверьте формат .env. Файл не изменён; значения скрыты.")
            value = value.strip()
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise SystemExit("BLOCKED: проверьте кавычки в .env. Файл не изменён; значения скрыты.")
                value = value[1:-1]
            existing[key.strip()] = value
        if any(not existing.get(key, "").strip() for key in REQUIRED_KEYS):
            raise SystemExit(
                "BLOCKED: в существующем .env отсутствует обязательный ключ или его значение. "
                "Файл не изменён; значения скрыты."
            )
        print("PASS: .env уже существует; обязательные ключи присутствуют; файл не изменён.")
        return

    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password.strip():
        raise SystemExit(
            "BLOCKED: действующий POSTGRES_PASSWORD отсутствует в этом PowerShell. "
            "Запустите файл в прежнем окне, где прошла интеграция. .env не создан."
        )
    django_key = os.environ.get("DJANGO_SECRET_KEY", "")
    if not django_key.strip():
        django_key = secrets.token_urlsafe(64)
    values = {"DJANGO_SECRET_KEY": django_key, "POSTGRES_PASSWORD": password}

    # Значения из интеграционного блока — Base64; исключаем интерполяцию и переносы строк.
    if any(not re.fullmatch(r"[A-Za-z0-9_+/=-]+", value) for value in values.values()):
        raise SystemExit(
            "BLOCKED: значения требуют отдельного экранирования. .env не создан; значения скрыты."
        )

    template = (root / ".env.example").read_text(encoding="utf-8-sig")
    template_keys = {line.partition("=")[0] for line in template.splitlines()}
    if not set(REQUIRED_KEYS).issubset(template_keys):
        raise SystemExit("BLOCKED: в .env.example отсутствует обязательный ключ. .env не создан.")

    lines = []
    for line in template.splitlines():
        key = line.partition("=")[0]
        lines.append(key + "=" + values[key] if key in values else line)

    # Режим x не позволяет перезаписать даже файл, появившийся во время проверки.
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines) + "\n")
    print("PASS: .env сохранён в корне проекта; действующий пароль сохранён; значения скрыты.")


if __name__ == "__main__":
    try:
        save_local_env(Path(__file__).resolve().parent)
    except OSError:
        raise SystemExit("BLOCKED: операция с .env не завершена. Значения секретов не выводились.") from None
