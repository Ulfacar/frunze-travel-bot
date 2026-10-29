#!/usr/bin/env python3
"""Архив Bitrix24 до конца подписки — ТОЛЬКО ЧТЕНИЕ (план отказа §3.3, B4-архив).

Выгружает в JSONL на сервере то, без чего после отключения портала пропадёт история:

    leads.jsonl     crm.lead.list            лиды (все поля, телефоны, UF_*)
    deals.jsonl     crm.deal.list            сделки
    contacts.jsonl  crm.contact.list         контакты (телефоны)
    timeline.jsonl  crm.timeline.comment.list комментарии таймлайна лида/сделки,
                                             одна строка = одна сущность со всеми комментариями

Принципы:

* **Только чтение.** Клиент пускает только четыре метода `*.list` из `ALLOWED_METHODS`;
  любой другой вызов — исключение до сети. В портал не пишется ничего.
* **Сухой режим по умолчанию.** Без `--yes` только считает, сколько записей будет
  выгружено (по одному запросу на тип), файлов не пишет.
* **Продолжение после обрыва.** Страницы идут по возрастанию ID с фильтром `>ID`
  (`start=-1`, рекомендованный Битриксом способ для больших выгрузок): сдвиг страниц
  при добавлении и удалении записей во время выгрузки не даёт ни дублей, ни пропусков.
  Курсор — `cursor.json`, но истина — сами файлы: при старте берётся наибольший ID,
  реально лежащий в файле, а оборванная последняя строка отрезается. Повторный
  запуск дописывает только недостающее.
* **Бережно к порталу.** Не больше `--rps` запросов в секунду (по умолчанию 1.0 при
  лимите портала 2). На 403/429/503 и `QUERY_LIMIT_EXCEEDED` / `OPERATION_TIME_LIMIT`
  — пауза с ростом до 15 минут (в сентябре портал отвечал 403 ночью 03:00–07:00).
  Исчерпали попытки — курсор сохранён, код выхода 3, запуск можно повторить утром.
* **Персональные данные.** Каталог 0700, файлы 0600. URL вебхука не печатается.

Запуск на сервере (вебхук из окружения, не в командной строке):

    BITRIX24_WEBHOOK_URL=... python scripts/bitrix_archive_export.py --out /root/bitrix-archive
    BITRIX24_WEBHOOK_URL=... python scripts/bitrix_archive_export.py --out /root/bitrix-archive --yes

Поиск по готовому архиву — `scripts/bitrix_archive_search.py`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ALLOWED_METHODS = frozenset({"crm.lead.list", "crm.deal.list", "crm.contact.list",
                             "crm.timeline.comment.list"})
PAGE = 50   # фиксированный размер страницы REST Битрикса

# Тип → (метод, файл, select). `*` не включает множественные поля и UF_* — их отдельно.
ENTITIES: dict[str, tuple[str, str, list[str]]] = {
    "lead": ("crm.lead.list", "leads.jsonl", ["*", "UF_*", "PHONE", "EMAIL", "IM"]),
    "deal": ("crm.deal.list", "deals.jsonl", ["*", "UF_*"]),
    "contact": ("crm.contact.list", "contacts.jsonl", ["*", "UF_*", "PHONE", "EMAIL", "IM"]),
}
TIMELINE_FOR = ("lead", "deal")       # чьи комментарии таймлайна берём
TIMELINE_FILE = "timeline.jsonl"

RETRY_STATUSES = {403, 429, 500, 502, 503, 504}
RETRY_ERRORS = {"QUERY_LIMIT_EXCEEDED", "OPERATION_TIME_LIMIT", "INTERNAL_SERVER_ERROR"}
BACKOFF = (5, 15, 30, 60, 120, 300, 600, 900, 900)   # секунды; ночное окно 403 ≈ 4 ч

EXIT_OK, EXIT_USAGE, EXIT_HTTP, EXIT_GAVE_UP = 0, 2, 4, 3


class ForbiddenMethod(RuntimeError):
    """Попытка вызвать что-то кроме разрешённых методов чтения."""


class GaveUp(RuntimeError):
    """Портал не ответил после всех пауз — курсор сохранён, повторить позже."""


class PortalError(RuntimeError):
    """Ответ, который не лечится повтором (неверный вебхук, нет прав на метод)."""


# Транспорт: (полный URL, тело) → (HTTP-статус, разобранный JSON или None).
Transport = Callable[[str, dict], tuple[int, Any]]


def httpx_transport(timeout: float = 30.0) -> Transport:
    import httpx
    client = httpx.Client(timeout=timeout)

    def post(url: str, payload: dict) -> tuple[int, Any]:
        resp = client.post(url, json=payload)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, None
    return post


@dataclass
class ReadOnlyBitrix:
    """REST-клиент, который физически не умеет писать: только методы из ALLOWED_METHODS."""

    base: str
    transport: Transport
    rps: float = 1.0
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    log: Callable[[str], None] = lambda m: print(m, file=sys.stderr)
    backoff: tuple[int, ...] = BACKOFF
    calls: int = 0
    waited: float = 0.0
    _last: float = field(default=-1e9, repr=False)

    def call(self, method: str, params: dict) -> dict:
        if method not in ALLOWED_METHODS:
            raise ForbiddenMethod(method)
        for attempt in range(len(self.backoff) + 1):
            self._throttle()
            self.calls += 1
            try:
                status, body = self.transport(f"{self.base.rstrip('/')}/{method}.json", params)
            except Exception as exc:  # noqa: BLE001 — сеть: повторяем как 503
                status, body = 599, {"error": type(exc).__name__}
            error = (body or {}).get("error") if isinstance(body, dict) else None
            if status == 200 and not error and isinstance(body, dict):
                return body
            retryable = status in RETRY_STATUSES or status == 599 or error in RETRY_ERRORS
            if not retryable:
                raise PortalError(f"{method}: HTTP {status} {error or ''}".strip())
            if attempt == len(self.backoff):
                break
            pause = self.backoff[attempt]
            self.log(f"{method}: HTTP {status} {error or ''} — пауза {pause} с "
                     f"(попытка {attempt + 1}/{len(self.backoff)})")
            self.waited += pause
            self.sleep(pause)
        raise GaveUp(f"{method}: портал не отвечает после {len(self.backoff)} пауз")

    def _throttle(self) -> None:
        gap = 1.0 / self.rps if self.rps > 0 else 0.0
        now = self.clock()
        wait = self._last + gap - now
        if wait > 0:
            self.sleep(wait)
            now += wait
        self._last = now


# ------------------------------- файлы и курсор -------------------------------

def _secure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _open_append(path: Path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.chmod(path, 0o600)
    return os.fdopen(fd, "a", encoding="utf-8")


def repair_tail(path: Path) -> int:
    """Отрезать оборванную последнюю строку (обрыв посреди записи). Возвращает байты."""
    if not path.exists():
        return 0
    data = path.read_bytes()
    if not data or data.endswith(b"\n"):
        return 0
    cut = data.rfind(b"\n") + 1
    with open(path, "r+b") as fh:
        fh.truncate(cut)
    return len(data) - cut


def max_id_in(path: Path, key: str = "ID") -> int:
    """Наибольший ID в JSONL — истина для продолжения, а не cursor.json."""
    best = 0
    if not path.exists():
        return best
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                best = max(best, int(json.loads(line).get(key) or 0))
            except (ValueError, json.JSONDecodeError):
                continue
    return best


def ids_in(path: Path, key: str = "ID") -> list[int]:
    out = []
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    out.append(int(json.loads(line)[key]))
    return out


def load_cursor(out: Path) -> dict:
    try:
        return json.loads((out / "cursor.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cursor(out: Path, cursor: dict) -> None:
    tmp = out / "cursor.json.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(cursor, fh, ensure_ascii=False, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, out / "cursor.json")


# ------------------------------- выгрузка -------------------------------

def count_entities(api: ReadOnlyBitrix) -> dict[str, int]:
    """Сухой режим: по одному запросу на тип, только `total`."""
    totals = {}
    for kind, (method, _file, _select) in ENTITIES.items():
        body = api.call(method, {"select": ["ID"], "order": {"ID": "ASC"}, "start": 0})
        totals[kind] = int(body.get("total") or len(body.get("result") or []))
    return totals


def export_entity(api: ReadOnlyBitrix, out: Path, kind: str, cursor: dict, *,
                  limit: int | None = None) -> int:
    """Постранично по ID. Возвращает число новых записей."""
    method, filename, select = ENTITIES[kind]
    path = out / filename
    repair_tail(path)
    last = max(int(cursor.get(kind, {}).get("last_id") or 0), max_id_in(path))
    written = 0
    while True:
        body = api.call(method, {"select": select, "order": {"ID": "ASC"},
                                 "filter": {">ID": last}, "start": -1})
        rows = body.get("result") or []
        fresh = sorted((r for r in rows if int(r.get("ID") or 0) > last),
                       key=lambda r: int(r["ID"]))
        # Дубликаты внутри страницы (портал при сдвиге может вернуть запись дважды).
        seen, page = set(), []
        for r in fresh:
            if r["ID"] not in seen:
                seen.add(r["ID"])
                page.append(r)
        if rows and not page:
            # Портал вернул только уже выгруженное — так быть не должно. Не объявляем
            # тип выгруженным: лучше остановиться, чем молча потерять хвост.
            raise PortalError(f"{method}: страница без новых ID после {last}")
        if not page:
            cursor[kind] = {"last_id": last, "done": True}
            save_cursor(out, cursor)
            return written
        with _open_append(path) as fh:
            for r in page:
                fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        last = int(page[-1]["ID"])
        written += len(page)
        cursor[kind] = {"last_id": last, "done": False}
        save_cursor(out, cursor)
        if len(rows) < PAGE or (limit is not None and written >= limit):
            if len(rows) < PAGE:
                cursor[kind] = {"last_id": last, "done": True}
                save_cursor(out, cursor)
            return written


def _timeline_done(path: Path) -> set[tuple[str, int]]:
    done = set()
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    done.add((rec["entity_type"], int(rec["entity_id"])))
    return done


def export_timeline(api: ReadOnlyBitrix, out: Path, cursor: dict, *,
                    limit: int | None = None) -> int:
    """Комментарии таймлайна: одна строка на сущность — либо целиком, либо нет."""
    path = out / TIMELINE_FILE
    repair_tail(path)
    done = _timeline_done(path)
    written = 0
    for kind in TIMELINE_FOR:
        for entity_id in ids_in(out / ENTITIES[kind][1]):
            if (kind, entity_id) in done:
                continue
            comments, start, seen = [], 0, set()
            while True:
                body = api.call("crm.timeline.comment.list", {
                    "filter": {"ENTITY_TYPE": kind, "ENTITY_ID": entity_id},
                    "select": ["ID", "CREATED", "AUTHOR_ID", "COMMENT", "FILES"],
                    "order": {"ID": "ASC"}, "start": start})
                for c in body.get("result") or []:
                    if c.get("ID") not in seen:
                        seen.add(c.get("ID"))
                        comments.append(c)
                nxt = body.get("next")
                if not nxt:
                    break
                start = int(nxt)
            rec = {"entity_type": kind, "entity_id": entity_id,
                   "comments": sorted(comments, key=lambda c: int(c.get("ID") or 0))}
            with _open_append(path) as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            done.add((kind, entity_id))
            written += 1
            cursor["timeline"] = {"last": [kind, entity_id]}
            save_cursor(out, cursor)
            if limit is not None and written >= limit:
                return written
    cursor["timeline"] = {"done": True}
    save_cursor(out, cursor)
    return written


def run(argv: list[str] | None = None, *, transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        stdout=None) -> int:
    p = argparse.ArgumentParser(description="Архив Bitrix24 в JSONL (только чтение)")
    p.add_argument("--out", required=True, help="каталог архива на сервере")
    p.add_argument("--yes", action="store_true", help="выгружать (без флага — только подсчёт)")
    p.add_argument("--rps", type=float, default=1.0, help="запросов в секунду (≤ 2)")
    p.add_argument("--only", default="lead,deal,contact,timeline",
                   help="что выгружать, через запятую")
    p.add_argument("--limit", type=int, default=None,
                   help="не больше N записей на тип за запуск (для пробного прогона)")
    p.add_argument("--webhook-env", default="BITRIX24_WEBHOOK_URL",
                   help="имя переменной окружения с URL вебхука")
    args = p.parse_args(argv)
    say = (lambda m: print(m, file=stdout)) if stdout is not None else print
    base = os.environ.get(args.webhook_env, "").strip()
    if not base:
        say(f"Нет вебхука: задайте {args.webhook_env}. В командной строке URL не принимаем.")
        return EXIT_USAGE
    if not 0 < args.rps <= 2:
        say("--rps должен быть в (0, 2]: лимит портала — 2 запроса в секунду.")
        return EXIT_USAGE
    only = [x.strip() for x in args.only.split(",") if x.strip()]
    unknown = [x for x in only if x not in (*ENTITIES, "timeline")]
    if unknown:
        say(f"Неизвестные типы: {unknown}")
        return EXIT_USAGE
    api = ReadOnlyBitrix(base=base, transport=transport or httpx_transport(), rps=args.rps,
                         sleep=sleep, clock=clock,
                         log=lambda m: say("  " + m))
    out = Path(args.out)
    try:
        if not args.yes:
            totals = count_entities(api)
            say("СУХОЙ РЕЖИМ — файлы не пишутся, в портал ничего не пишется.")
            for kind, n in totals.items():
                say(f"  {kind}: {n} записей → {-(-n // PAGE)} запросов")
            timeline_calls = sum(totals[k] for k in TIMELINE_FOR if k in totals)
            pages = sum(-(-n // PAGE) for n in totals.values())
            est = (pages + timeline_calls) / args.rps
            say(f"  timeline: не меньше {timeline_calls} запросов (по одному на лид и сделку)")
            say(f"  Оценка без пауз: {pages + timeline_calls} запросов ≈ {est / 60:.0f} мин "
                f"при {args.rps} запр./с. Запустить выгрузку: добавьте --yes")
            return EXIT_OK
        _secure_dir(out)
        cursor = load_cursor(out)
        cursor.setdefault("started_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        for kind in ENTITIES:
            if kind in only:
                n = export_entity(api, out, kind, cursor, limit=args.limit)
                say(f"  {kind}: +{n}, всего {len(ids_in(out / ENTITIES[kind][1]))}")
        if "timeline" in only:
            n = export_timeline(api, out, cursor, limit=args.limit)
            say(f"  timeline: +{n} сущностей")
        cursor["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cursor["calls"] = cursor.get("calls", 0) + api.calls
        save_cursor(out, cursor)
        say(f"Готово: запросов {api.calls}, пауз {api.waited:.0f} с. Каталог: {out}")
        return EXIT_OK
    except GaveUp as exc:
        say(f"ОСТАНОВЛЕНО: {exc}. Курсор сохранён — повторите запуск позже.")
        return EXIT_GAVE_UP
    except PortalError as exc:
        say(f"ОШИБКА ПОРТАЛА: {exc}. Проверьте вебхук и права (только чтение CRM).")
        return EXIT_HTTP


if __name__ == "__main__":
    sys.exit(run())
