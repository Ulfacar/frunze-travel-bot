#!/usr/bin/env python
"""Детерминированный гейт прод-ловушек — код, а не агент.

Зачем: у нас есть повторяющийся класс аварий, который тесты НЕ ловят, потому что
локально всё зелёное, а на проде настройка просто не существует.

  * `475e2f7` — настройку положили в prod.env, но забыли дописать в `environment:`
    docker-compose. Контейнер видит ТОЛЬКО перечисленное там. На проде — дефолт,
    молча, без ошибки.
  * Новый рантайм-флаг заведён в коде, но не зарегистрирован в `FEATURE_FLAGS` —
    тумблера в админке нет, включить/выключить без деплоя нельзя.

Скрипт сверяет три источника правды и падает с кодом 1, если они разъехались:

  app/config.py (Settings)  <->  docker-compose.yml (environment:)  <->  .env

Запуск:
    python scripts/prod_traps_check.py                    # обзор, WARN не валят
    python scripts/prod_traps_check.py --strict           # любая находка = провал
    python scripts/prod_traps_check.py --diff-base HEAD   # только то, что добавили
    python scripts/prod_traps_check.py --env-file prod.env

`--diff-base` — главный режим для Венома: новые настройки из текущего диффа
обязаны быть в compose. Это ERROR, а не WARN: ровно на этом обожглись.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Поля Settings, которых в compose нет намеренно: дев-онли, вычисляемые или
# переопределяемые самим compose (DATABASE_URL/REDIS_URL смотрят на сервисы db/redis).
COMPOSE_EXEMPT = {
    "DATABASE_URL", "REDIS_URL", "POSTGRES_PASSWORD",
    "APP_ENV", "LOG_LEVEL", "DEBUG",
}

# Флаги, которые заведомо динамические (`stt_enabled:<bot_id>`, `bots_enabled:<id>`)
# — у них в админке свой отдельный экран, в FEATURE_FLAGS их нет и не должно быть.
FLAG_EXEMPT = {
    "bots_enabled", "stt_enabled", "manager_off", "stt_public_enabled",
    # пер-ботовый, глобального тумблера намеренно нет: включить блокировку сразу всем
    # ботам одной кнопкой — не та ошибка, которую стоит делать лёгкой
    "stt_guard_block",
}


class Finding:
    def __init__(self, level: str, code: str, item: str, hint: str) -> None:
        self.level, self.code, self.item, self.hint = level, code, item, hint

    def __str__(self) -> str:
        return f"[{self.level}] {self.code}: {self.item}\n         {self.hint}"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def settings_fields() -> set[str]:
    """Поля класса Settings из app/config.py -> имена env-переменных (UPPER)."""
    text = _read(ROOT / "app" / "config.py")
    if not text:
        return set()
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith("class Settings("))
    except StopIteration:
        return set()
    fields: set[str] = set()
    for ln in lines[start + 1:]:
        if ln and not ln.startswith((" ", "\t", ")")):
            break                                    # вышли из класса
        stripped = ln.strip()
        if not stripped or stripped.startswith(("#", "@", "def ", "class ", '"""', "'''")):
            continue
        m = re.match(r"^ {4}([a-z_][a-z0-9_]*)\s*:\s*[^=\s]", ln)
        if m and m.group(1) != "model_config":
            fields.add(m.group(1).upper())
    return fields


def used_settings() -> set[str]:
    """Поля, которые код где-либо упоминает, -> UPPER.

    Нужно, чтобы отличать «настройка не доедет на прод» (авария) от «настройка
    объявлена и забыта» (мусор). Разная срочность — разный уровень находки.

    Ищем имя поля как отдельное слово, а НЕ `settings.<field>`: код обращается к
    конфигу под разными псевдонимами (`cfg.followup_after_hours`,
    `getattr(cfg, "followup_after_hours", 24)`). Узкий шаблон объявил бы живые
    настройки мёртвыми — а гейт, который врёт, хуже отсутствующего. Поэтому
    ошибаемся в безопасную сторону: лишний раз посчитать используемой не страшно.
    """
    blob = "\n".join(_read(py) for py in (ROOT / "app").rglob("*.py")
                     if py.name != "config.py")
    words = set(re.findall(r"[a-z_][a-z0-9_]*", blob))
    return {w.upper() for w in words}


def compose_env_keys(compose: Path, service: str = "app") -> set[str]:
    """Ключи из блока `environment:` нужного сервиса docker-compose."""
    text = _read(compose)
    if not text:
        return set()
    keys: set[str] = set()
    in_service = in_env = False
    for ln in text.splitlines():
        if re.match(r"^ {2}[a-z0-9_-]+:\s*$", ln):          # начало сервиса
            in_service = ln.strip().rstrip(":") == service
            in_env = False
            continue
        if not in_service:
            continue
        if re.match(r"^ {4}environment:\s*$", ln):
            in_env = True
            continue
        if in_env:
            if ln.strip() and not re.match(r"^ {6,}", ln):   # дедент — блок кончился
                in_env = False
                continue
            m = re.match(r"^ {6,}([A-Z][A-Z0-9_]*)\s*:", ln)
            if m:
                keys.add(m.group(1))
    return keys


def env_file_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for ln in _read(path).splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        m = re.match(r"^([A-Z][A-Z0-9_]*)\s*=", ln)
        if m:
            keys.add(m.group(1))
    return keys


def flags_used() -> set[str]:
    """Литеральные имена рантайм-флагов из вызовов flags.get_flag("...")."""
    used: set[str] = set()
    for py in (ROOT / "app").rglob("*.py"):
        for m in re.finditer(r'get_flag\(\s*"([a-z][a-z0-9_]*)"', _read(py)):
            used.add(m.group(1))
    return used


def flags_registered() -> set[str]:
    """Ключи FEATURE_FLAGS — то, у чего есть тумблер в админке."""
    text = _read(ROOT / "app" / "admin" / "router.py")
    m = re.search(r"^FEATURE_FLAGS\s*=\s*\{(.*?)^\}", text, re.S | re.M)
    return set(re.findall(r'^\s{4}"([a-z][a-z0-9_]*)"\s*:', m.group(1), re.M)) if m else set()


def added_settings(diff_base: str) -> set[str]:
    """Поля Settings, ДОБАВЛЕННЫЕ относительно базы (git diff app/config.py)."""
    try:
        out = subprocess.run(
            ["git", "diff", diff_base, "--", "app/config.py"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {m.group(1).upper()
            for m in re.finditer(r"^\+ {4}([a-z_][a-z0-9_]*)\s*:\s*[^=\s]", out, re.M)}


def run(args: argparse.Namespace) -> list[Finding]:
    compose = ROOT / args.compose
    fields = settings_fields()
    env_keys = compose_env_keys(compose)
    new_fields = added_settings(args.diff_base) if args.diff_base else set()
    findings: list[Finding] = []

    if not fields or not env_keys:
        findings.append(Finding("ERROR", "PARSE", f"{args.compose} / app/config.py",
                                "не удалось прочитать источники — гейт бесполезен, чини скрипт"))
        return findings

    used = used_settings()

    # 1. Настройка есть в коде, но в контейнер попасть не может.
    for name in sorted(fields - env_keys - COMPOSE_EXEMPT):
        if name not in used:
            findings.append(Finding("WARN", "DEAD_SETTING", name,
                                    "объявлена в Settings, но нигде не читается — удали или используй"))
            continue
        is_new = name in new_fields
        findings.append(Finding(
            "ERROR" if is_new else "WARN", "NOT_IN_COMPOSE", name,
            f"добавь `{name}: ${{{name}:-<дефолт>}}` в environment: сервиса app "
            f"({args.compose})" + (" — НОВАЯ в этом диффе" if is_new else
                                   " — на проде переопределить нельзя")))

    # 2. Ключ задан в env-файле, приложение его читает, но в контейнер он не доедет.
    #    Сверяем ТОЛЬКО с полями Settings: чужие ключи (дев-инструменты, ключи других
    #    сервисов) приложение не читает, и их отсутствие в compose — не авария.
    env_path = ROOT / args.env_file
    if env_path.exists():
        for name in sorted(env_file_keys(env_path) & fields & used - env_keys - COMPOSE_EXEMPT):
            findings.append(Finding(
                "ERROR", "SET_BUT_NOT_DELIVERED", name,
                f"есть в {args.env_file} и читается Settings, но нет в environment: "
                f"— контейнер его НЕ увидит, приложение возьмёт дефолт"))

    # 3. Мусор в compose: переменная есть, поля под неё нет.
    for name in sorted(env_keys - fields - COMPOSE_EXEMPT):
        findings.append(Finding("WARN", "COMPOSE_ORPHAN", name,
                                "в compose есть, в Settings нет — опечатка или мёртвая настройка"))

    # 4. Флаг используется в коде, но тумблера в админке нет.
    for name in sorted(flags_used() - flags_registered() - FLAG_EXEMPT):
        findings.append(Finding("WARN", "FLAG_WITHOUT_TOGGLE", name,
                                "нет в FEATURE_FLAGS — переключить без деплоя не выйдет"))

    return findings


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Гейт прод-ловушек Frunze Travel")
    p.add_argument("--compose", default="docker-compose.yml")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--diff-base", default="", help="git-ref: новые настройки = ERROR")
    p.add_argument("--strict", action="store_true", help="WARN тоже валит прогон")
    p.add_argument("--limit", type=int, default=10, help="сколько WARN печатать (0 = все)")
    args = p.parse_args()

    findings = run(args)
    errors = [f for f in findings if f.level == "ERROR"]
    warns = [f for f in findings if f.level == "WARN"]

    shown = warns if args.limit <= 0 else warns[:args.limit]
    for f in errors + shown:
        print(f)
    if len(shown) < len(warns):
        print(f"\n... и ещё {len(warns) - len(shown)} WARN (полный список: --limit 0)")
    print(f"\nИтог: {len(errors)} ERROR, {len(warns)} WARN")

    failed = bool(errors) or (args.strict and bool(warns))
    print("ГЕЙТ ПРОВАЛЕН" if failed else "ГЕЙТ ПРОЙДЕН")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
