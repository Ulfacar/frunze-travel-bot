"""Локальный запуск админки для просмотра вида — без прода и без боевых данных.

Зачем. Вид панели нельзя принять по скриншоту: надо открыть, потыкать вкладки, потащить
карточку, включить тёмную тему. Этот скрипт поднимает настоящее приложение на localhost
с памятью вместо базы и засевает правдоподобные диалоги, чтобы доска была не пустой.

Боевых данных здесь нет вообще: ни одного реального номера, ни одного реального клиента.
Никаких сетевых интеграций — бот не отвечает, Bitrix и TourVisor не вызываются.

    python scripts/run_admin_local.py              # новый вид
    python scripts/run_admin_local.py --old        # прежний вид, для сравнения
    python scripts/run_admin_local.py --port 8099

Логин: admin / admin
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _configure(new_look: bool, port: int) -> None:
    """Настройки до импорта приложения: оно читает их на старте."""
    os.environ["PANEL_BACKEND"] = "memory"
    os.environ["CRM_BACKEND"] = "stub"
    os.environ["ADMIN_ENABLED"] = "true"
    os.environ["SESSION_SECRET"] = "local-preview-not-a-secret"
    # Cookie сессии на проде идёт с Secure (там TLS). По http на localhost браузер
    # такую cookie не сохранит, и войти в панель нельзя — поэтому здесь выключаем.
    os.environ["SESSION_HTTPS_ONLY"] = "false"
    os.environ["ADMIN_NEW_LOOK_ENABLED"] = "true" if new_look else "false"
    os.environ["ADMIN_INBOX_LIMIT_ENABLED"] = "true"
    os.environ["ADMIN_FOCUS_ENABLED"] = "true" if new_look else "false"
    os.environ["MANAGERS"] = (
        '[{"login":"admin","name":"Алан","password":"admin","admin":true}]')
    os.environ.setdefault("PUBLIC_BASE_URL", f"http://127.0.0.1:{port}")


# Правдоподобные, но вымышленные диалоги: те же формы реплик, что на проде.
TOURS = [
    ("Азамат К.", "996700440021", "Здравствуйте, а тур в Турцию на двоих в октябре сколько?", "client", 165),
    ("Гулназ С.", "996555197340", "Подобрал пять вариантов по Аланье, посмотрите подборку", "bot", 40),
    ("Нурия Б.", "996707110255", "https://instagram.com/p/Cxyz Можно узнать об этом подробнее?", "client", 12),
    ("Тилек Ж.", "996550831429", "Нам вдвоём, вылет 22 октября, бюджет до 2000", "client", 52),
    ("Бермет А.", "996772640118", "А если на 10 ночей, сильно дороже выйдет?", "client", 310),
    ("Эрмек Т.", "996500773901", "Спасибо, подумаем и напишем", "client", 2880),
]
VISA = [
    ("Айпери М.", "996709220514", "Виза в США, что нужно для записи на собеседование?", "client", 95),
    ("Руслан Д.", "996777340962", "Документы собрал, когда можно подъехать в офис?", "client", 25),
    ("Жылдыз О.", "996555880173", "Шенген делаете? Нужен в Италию в ноябре", "client", 480),
    ("Данияр Ш.", "996700615248", "Записал вас на 14 октября, 10:30. Паспорт и ID не забудьте", "manager", 1440),
]
STAGES_TOURS = ["greeting", "qualification", "progress", "office", "manager", "follow_up"]
STAGES_VISA = ["greeting", "qualification", "progress", "office", "manager"]


async def _seed() -> None:
    from app.integrations.panel.store import get_conversation_store
    store = get_conversation_store()
    now = datetime.now(timezone.utc)
    rnd = random.Random(20261002)

    async def add(bot_id, funnel, stages, rows):
        for i, (name, phone, text, sender, minutes_ago) in enumerate(rows):
            user = f"{bot_id}:{phone}"
            await store.add_message(user, sender, text, channel="whatsapp",
                                    bot_id=bot_id, phone=phone)
            conv = store._conv[user] if hasattr(store, "_conv") else None
            if conv is not None:
                conv.last_message_at = now - timedelta(minutes=minutes_ago)
                for m in conv.messages:
                    m.created_at = now - timedelta(minutes=minutes_ago)
            await store.update_meta(
                user, funnel=funnel, stage=stages[i % len(stages)],
                qualification={"name": name},
                lead_temperature=rnd.choice(["new", "warm", "hot"]),
                assigned_to=rnd.choice(["", "medina", "eliza", "ademi"]),
            )

    await add("frunze_tours", "tours", STAGES_TOURS, TOURS)
    await add("getvisa", "visa", STAGES_VISA, VISA)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--old", action="store_true", help="прежний вид вместо нового")
    args = parser.parse_args()

    _configure(new_look=not args.old, port=args.port)

    import uvicorn
    from app.main import app

    asyncio.run(_seed())
    look = "ПРЕЖНИЙ" if args.old else "НОВЫЙ"
    print(f"\n  Вид: {look}")
    print(f"  Панель:  http://127.0.0.1:{args.port}/admin")
    if not args.old:
        print(f"  Фокус:   http://127.0.0.1:{args.port}/admin/focus")
    print(f"  Логин:   admin / admin")
    print(f"  Данные:  {len(TOURS) + len(VISA)} вымышленных диалога в памяти процесса\n")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
