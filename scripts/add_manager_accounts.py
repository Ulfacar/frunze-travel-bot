#!/usr/bin/env python3
"""Завести учётки менеджеров панели в `prod.env`. Запускать НА СЕРВЕРЕ, не в контейнере.

Зачем отдельный скрипт, а не правка руками: `MANAGERS` — это одна длинная строка JSON
с паролями всех менеджеров. Редактировать её в редакторе на боевом сервере значит
рисковать всем списком сразу: одна лишняя запятая — и панель остаётся без логинов, а
`/health` при этом зелёный (ровно эта ловушка описана в CLAUDE.md §4 про `--env-file`).

Что делает:
  * читает `MANAGERS`, добавляет только тех, кого там ещё нет;
  * существующие учётки не трогает — ни паролей, ни имён, ни признака админа;
  * генерирует пароль каждому новому и кладёт его в файл рядом с `prod.env` с правами
    0600 (как `first-login.json` для CRM 14.10.2026). В stdout пароли НЕ печатаются,
    поэтому их не видно ни в логе терминала, ни в отчёте агента;
  * делает резервную копию `prod.env` перед записью.

После него нужен рестарт приложения: `MANAGERS` читается из окружения при старте.

    python3 scripts/add_manager_accounts.py daulet:Даулет marsel:Марсель
    python3 scripts/add_manager_accounts.py --dry-run daulet:Даулет
    python3 scripts/add_manager_accounts.py --admin grisha-admin2:Гриша

`--dry-run` ничего не пишет и показывает, что изменилось бы.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import secrets
import shutil
import string
from datetime import date

ALPHABET = string.ascii_letters + string.digits      # без спецсимволов: вводить руками
PASSWORD_LENGTH = 12


def make_password() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(PASSWORD_LENGTH))


def parse_spec(spec: str) -> tuple[str, str]:
    login, _, name = spec.partition(":")
    login = login.strip().lower()
    if not login:
        raise argparse.ArgumentTypeError(f"пустой логин в {spec!r}")
    return login, (name.strip() or login)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("accounts", nargs="+", type=parse_spec,
                    help="логин:Имя (имя необязательно)")
    ap.add_argument("--env", default="/root/frunze-travel/prod.env")
    ap.add_argument("--admin", action="store_true",
                    help="полный доступ ко всем воронкам (как grisha-admin)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env_path = pathlib.Path(args.env)
    if not env_path.exists():
        print(f"НЕВОЗМОЖНО: {env_path} не найден")
        return 2

    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    index = next((i for i, line in enumerate(lines) if line.startswith("MANAGERS=")), None)
    if index is None:
        print("НЕВОЗМОЖНО: строки MANAGERS= в файле нет — ничего не менял")
        return 2

    raw = lines[index][len("MANAGERS="):].strip()
    quote = ""
    if raw[:1] in ("'", '"') and raw[-1:] == raw[:1]:
        quote, raw = raw[:1], raw[1:-1]
    try:
        managers = json.loads(raw)
    except ValueError as exc:
        print(f"НЕВОЗМОЖНО: MANAGERS не разбирается как JSON ({exc}) — ничего не менял")
        return 2
    if not isinstance(managers, list):
        print("НЕВОЗМОЖНО: MANAGERS не список — ничего не менял")
        return 2

    have = {str(m.get("login", "")).strip().lower() for m in managers}
    print(f"сейчас учёток: {len(managers)} — {', '.join(sorted(have))}")

    created: dict[str, str] = {}
    for login, name in args.accounts:
        if login in have:
            print(f"  {login}: уже есть, пропускаю")
            continue
        password = make_password()
        managers.append({"login": login, "name": name, "password": password,
                         "admin": bool(args.admin), "telegram_chat_id": ""})
        created[login] = password
        print(f"  {login}: будет заведён (имя {name!r}, admin={bool(args.admin)})")

    if not created:
        print("новых учёток нет — файл не тронут")
        return 0
    if args.dry_run:
        print("\n--dry-run: ничего не записано")
        return 0

    backup = env_path.with_suffix(env_path.suffix + f".bak-{date.today():%Y-%m-%d}-accounts")
    shutil.copy2(env_path, backup)
    lines[index] = f"MANAGERS={quote}{json.dumps(managers, ensure_ascii=False)}{quote}\n"
    env_path.write_text("".join(lines), encoding="utf-8")

    out = env_path.with_name(f"new-logins-{date.today():%Y-%m-%d}.json")
    existing = {}
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
        except ValueError:
            existing = {}
    out.write_text(json.dumps({**existing, **created}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    out.chmod(0o600)

    print(f"\nготово: учёток стало {len(managers)}, копия прежнего файла — {backup.name}")
    print(f"пароли записаны в {out} (права 0600); в этот вывод они не попадают")
    print("ТЕПЕРЬ НУЖЕН РЕСТАРТ: MANAGERS читается при старте приложения")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
