#!/usr/bin/env python3
"""Перевести пароли менеджеров в `prod.env` из открытого текста в хеши.

Запускать НА СЕРВЕРЕ. Вход при этом не ломается: `app.core.passwords.verify_password`
понимает оба формата, поэтому переводить можно по одному человеку и в любой момент —
не «все разом ночью перед показом».

Что делает:
  * читает `MANAGERS`, хеширует пароли тех, кто ещё в открытом виде;
  * уже захешированных не трогает (повторный запуск безопасен);
  * делает резервную копию `prod.env` рядом;
  * в stdout печатает ТОЛЬКО логины и факт перевода — ни одного пароля.

После него нужен рестарт приложения: `MANAGERS` читается при старте.

    python3 scripts/hash_manager_passwords.py --dry-run
    python3 scripts/hash_manager_passwords.py                 # всех разом
    python3 scripts/hash_manager_passwords.py --only medina   # по одному

ВАЖНО: после перевода открытый пароль нигде не остаётся. Раздайте людям пароли
ДО запуска (или заведите их заново через add_manager_accounts.py) — восстановить из
хеша нельзя, только назначить новый.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.core.passwords import hash_password, looks_hashed  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default="/root/frunze-travel/prod.env")
    ap.add_argument("--only", action="append", default=[],
                    help="перевести только этих (логин); можно повторять")
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

    only = {str(x).strip().lower() for x in args.only}
    changed, skipped_hashed, skipped_empty = [], [], []
    for mgr in managers:
        login = str(mgr.get("login", "")).strip().lower()
        if only and login not in only:
            continue
        password = str(mgr.get("password", "") or "")
        if looks_hashed(password):
            skipped_hashed.append(login)
            continue
        if not password:
            # Пустой пароль не хешируем: такой хеш означал бы вход без пароля.
            skipped_empty.append(login)
            continue
        mgr["password"] = hash_password(password)
        changed.append(login)

    print(f"учёток в файле: {len(managers)}")
    print(f"  будет переведено: {', '.join(changed) or 'никого'}")
    if skipped_hashed:
        print(f"  уже с хешем: {', '.join(skipped_hashed)}")
    if skipped_empty:
        # Без эмодзи: скрипт запускают и из Windows-терминала в cp1251, где любой
        # значок роняет вывод исключением — а это выглядит как сбой перевода паролей.
        print(f"  ВНИМАНИЕ, пустой пароль, пропущены: {', '.join(skipped_empty)}")
    if not changed:
        print("менять нечего — файл не тронут")
        return 0
    if args.dry_run:
        print("\n--dry-run: ничего не записано")
        return 0

    backup = env_path.with_suffix(env_path.suffix + f".bak-{date.today():%Y-%m-%d}-hash")
    shutil.copy2(env_path, backup)
    lines[index] = f"MANAGERS={quote}{json.dumps(managers, ensure_ascii=False)}{quote}\n"
    env_path.write_text("".join(lines), encoding="utf-8")

    print(f"\nготово: переведено {len(changed)}, копия прежнего файла — {backup.name}")
    print("ТЕПЕРЬ НУЖЕН РЕСТАРТ: MANAGERS читается при старте приложения")
    print("Открытых паролей в файле больше нет — восстановить их нельзя, "
          "только назначить новые.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
