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
    python3 scripts/add_manager_accounts.py "daulet-admin:Даулет (админ):admin"

Роль задаётся ТРЕТЬИМ полем у конкретной учётки (`:admin`), а не общим ключом: флаг
`--admin` действует на все учётки запуска, и одной командой «daulet, marsel и
daulet-admin» можно было случайно сделать полными админами всех троих. `--admin`
оставлен для совместимости, но в одной команде с ролями его лучше не смешивать.

`--dry-run` ничего не пишет и показывает, что изменилось бы.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import secrets
import shutil
import string
from datetime import date, datetime

ALPHABET = string.ascii_letters + string.digits      # для --random: вводить руками
PASSWORD_LENGTH = 12

# Пароли вида «limon-kedr-okean-42». Просьба Алана 11.11.2026: менеджеры далеки от
# компьютера, и строку «aB3kX9mQ2wZ1» они будут набирать с ошибками, а в итоге
# запишут на бумажке у монитора — это хуже любой энтропии. Слова короткие, без
# похожих букв и без «ы/ъ»-звуков, которые трудно продиктовать по телефону.
#
# Запас стойкости: 120 слов в трёх позициях плюс две цифры — порядка 1.5e8 вариантов,
# и вход в панель ограничен лимитером попыток. Для внутренней панели на семь человек
# этого достаточно; --random оставлен на случай, если захочется прежние случайные.
WORDS = (
    "almaz araket asman bagys balyk bereke bilim birge bulak chabyt chynar daryja "
    "dastan dubai egiz elbek erkin fakel garaj gazyr gulnar ikram jaiyk jalyn jarkyn "
    "jebe jolbors kadam kagaz kaimak kairat kanat kapchagai karlygach kedr kerben "
    "kezek kirgiz kochkor kolibri komuz korgon koshkar kumtor kurak kyial kyzyl "
    "limon maral marmar meken munara murok naryn nurbek okean olcha orozo osmon "
    "otton ozgon pamir pishpek rahat rezeda salkyn samal sanjyra sapar sary semetei "
    "serik shabdal shamal sherne shukur sulu suluu syrga talas talgat tamga tanysh "
    "tashkent temir tilek tokmok tolkun tulpar turan ulan ulut umut urmat uzak "
    "vodopad yrys zamir zaman zarina zhibek zhyldyz zhyrgal zooluu zyia aktilek "
    "ayana baatyr chatyr degen erke firuza gulmira hanska"
).split()


def make_password() -> str:
    """Три слова и две цифры: «limon-kedr-okean-42». Диктуется по телефону."""
    words = [secrets.choice(WORDS) for _ in range(3)]
    return "-".join(words) + f"-{secrets.randbelow(90) + 10}"


def make_random_password() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(PASSWORD_LENGTH))


def parse_spec(spec: str) -> tuple[str, str, bool]:
    """`логин`, `логин:Имя` или `логин:Имя:admin` → (логин, имя, полный ли админ)."""
    parts = spec.split(":")
    login = parts[0].strip().lower()
    if not login:
        raise argparse.ArgumentTypeError(f"пустой логин в {spec!r}")
    name = (parts[1].strip() if len(parts) > 1 else "") or login
    role = (parts[2].strip().lower() if len(parts) > 2 else "")
    if role and role != "admin":
        raise argparse.ArgumentTypeError(
            f"третьим полем бывает только 'admin', а не {role!r} (в {spec!r})")
    return login, name, role == "admin"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("accounts", nargs="+", type=parse_spec,
                    help="логин[:Имя[:admin]] — роль задаётся у конкретной учётки")
    ap.add_argument("--env", default="/root/frunze-travel/prod.env")
    ap.add_argument("--admin", action="store_true",
                    help="полный доступ ВСЕМ учёткам запуска (устарело: лучше ':admin' "
                         "у нужной учётки, иначе легко раздать права лишним людям)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--random", action="store_true",
                    help="прежние случайные пароли вида aB3kX9mQ2wZ1 вместо словесных")
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
    for login, name, is_admin in args.accounts:
        if login in have:
            print(f"  {login}: уже есть, пропускаю")
            continue
        full_admin = bool(is_admin or args.admin)
        password = make_random_password() if args.random else make_password()
        managers.append({"login": login, "name": name, "password": password,
                         "admin": full_admin, "telegram_chat_id": ""})
        created[login] = password
        flag = "ПОЛНЫЙ АДМИН" if full_admin else "обычный менеджер"
        print(f"  {login}: будет заведён (имя {name!r}, {flag})")

    if not created:
        print("новых учёток нет — файл не тронут")
        return 0
    if args.dry_run:
        print("\n--dry-run: ничего не записано")
        return 0

    # Бэкап с ВРЕМЕНЕМ, а не только датой: второй запуск в тот же день перезаписывал
    # бы копию уже изменённым файлом, и глубина отката становилась нулевой.
    backup = env_path.with_suffix(
        env_path.suffix + f".bak-{datetime.now():%Y-%m-%d-%H%M%S}-accounts")
    shutil.copy2(env_path, backup)
    lines[index] = f"MANAGERS={quote}{json.dumps(managers, ensure_ascii=False)}{quote}\n"

    # Запись АТОМАРНАЯ: временный файл рядом, fsync, затем os.replace. Прежняя
    # write_text обрезала боевой файл на месте, и обрыв на середине (нет места,
    # Ctrl-C, OOM, ребут) оставлял prod.env без ВСЕХ секретов — токенов Wappi, ключа
    # LLM, вебхука Bitrix, пароля базы. Приложение после такого не поднимется, а
    # деплой откатывает код, но не этот файл. Найдено аудитом 12.11.2026.
    tmp = env_path.with_suffix(env_path.suffix + ".tmp-accounts")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("".join(lines))
        fh.flush()
        os.fsync(fh.fileno())
    shutil.copymode(env_path, tmp)
    os.replace(tmp, env_path)

    # Перечитываем и разбираем: если запись вышла битой, возвращаем бэкап сами, а не
    # оставляем человека с нерабочим прод-файлом в руках.
    try:
        check = [line for line in env_path.read_text(encoding="utf-8").splitlines()
                 if line.startswith("MANAGERS=")]
        if len(check) != 1:
            raise ValueError(f"строк MANAGERS= стало {len(check)}, должна быть одна")
        probe = check[0][len("MANAGERS="):].strip()
        if probe[:1] in ("'", chr(34)) and probe[-1:] == probe[:1]:
            probe = probe[1:-1]
        if len(json.loads(probe)) != len(managers):
            raise ValueError("после записи в MANAGERS другое число учёток")
    except Exception as exc:  # noqa: BLE001 — любая беда = возвращаем как было
        shutil.copy2(backup, env_path)
        print(f"ЗАПИСЬ НЕ УДАЛАСЬ ({exc}) — файл возвращён из {backup.name}")
        return 2

    out = env_path.with_name(f"new-logins-{date.today():%Y-%m-%d}.json")
    existing = {}
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
        except ValueError:
            existing = {}
    # Открываем сразу с 0600: между записью и chmod файл с паролями был бы читаем
    # по umask — короткое, но настоящее окно (аудит 12.11.2026).
    payload = json.dumps({**existing, **created}, ensure_ascii=False, indent=2) + "\n"
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(payload)

    print(f"\nготово: учёток стало {len(managers)}, копия прежнего файла — {backup.name}")
    print(f"пароли записаны в {out} (права 0600); в этот вывод они не попадают")
    print("ТЕПЕРЬ НУЖЕН РЕСТАРТ: MANAGERS читается при старте приложения")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
