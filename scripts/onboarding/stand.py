"""Локальный стенд панели для скриншотов онбординга. ТОЛЬКО локально, только выдуманные данные.

Что делает:
* блокирует любые сетевые соединения наружу (кроме 127.0.0.1) — Wappi, Bitrix, LLM недостижимы;
* обнуляет все токены из локального .env;
* панель в памяти (как pw_panel.py), доменная база (задачи, касания, дела) — SQLite-файл рядом;
* включает ровно те функции, что включены на проде (список PROD_ON), остальные выключены;
* учётки как на проде: medina, daulet, marsel (не админы), grisha-admin (админ). Пароль у всех: demo;
* отправка клиенту «понарошку»: сообщение помечается отправленным, наружу ничего не уходит;
* засевает вымышленных клиентов (номера 996700000xxx) и касания через настоящую джобу touches.run.

Запуск:  .venv\\Scripts\\python.exe stand.py            (держит сервер на http://127.0.0.1:8111)
Скрины:  .venv\\Scripts\\python.exe shots.py            (при запущенном стенде)
"""
import asyncio
import ipaddress
import os
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("STAND_PORT", "8111"))
sys.path.insert(0, REPO)
os.chdir(REPO)

# --- 1. Сеть наружу закрыта ---------------------------------------------------------
_real_connect = socket.socket.connect
_real_getaddrinfo = socket.getaddrinfo


def _local(host) -> bool:
    host = str(host)
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _guard_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _local(address[0]):
        raise OSError(f"stand: внешняя сеть закрыта ({address[0]})")
    return _real_connect(self, address)


def _guard_getaddrinfo(host, *a, **k):
    if host is not None and not _local(host):
        raise OSError(f"stand: внешняя сеть закрыта ({host})")
    return _real_getaddrinfo(host, *a, **k)


socket.socket.connect = _guard_connect
socket.getaddrinfo = _guard_getaddrinfo

# --- 2. Настройки ---------------------------------------------------------------------
import app.config
from app.config import ManagerConfig

s = app.config.settings
for secret in ("openrouter_api_key", "anthropic_api_key", "telegram_bot_token", "wappi_token",
               "stt_api_key", "bitrix24_webhook_url", "managers_telegram_bot_token",
               "tourvisor_login", "tourvisor_pass"):
    if hasattr(s, secret):
        setattr(s, secret, "")
s.wappi_base_url = "http://127.0.0.1:9"
if hasattr(s, "telegram_bots"):
    s.telegram_bots = []
import tempfile
DB_FILE = os.path.join(tempfile.gettempdir(), "frunze-onboarding-stand.db")   # не в репо
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
s.database_url = "sqlite+aiosqlite:///" + DB_FILE.replace("\\", "/")
s.panel_backend = "memory"
s.state_backend = "memory"
s.crm_backend = "stub"
s.demo_login = False
s.crm_standalone_enabled = False
s.managers = [
    ManagerConfig(login="medina", name="Медина", password="demo"),
    ManagerConfig(login="daulet", name="Даулет", password="demo"),
    ManagerConfig(login="marsel", name="Марсель", password="demo"),
    ManagerConfig(login="grisha-admin", name="Гриша (админ)", password="demo", admin=True),
]

PROD_ON = ["admin_new_look_enabled", "admin_chat_redesign_enabled", "admin_focus_enabled",
           "admin_workday_enabled", "service_cases_enabled", "panel_send_media_enabled",
           "pilot_reply_queue_enabled", "admin_inbox_limit_enabled", "panel_simple_mode_enabled",
           "board_columns_by_direction_enabled", "visa_touch_tasks_enabled",
           "panel_pilot_summary_enabled", "lost_reason_enabled", "visa_card_fields_enabled",
           "panel_fresh_first_enabled", "panel_board_column_cap_enabled"]
PROD_OFF = ["panel_reports_enabled", "auto_stage_on_manager_reply_enabled",
            "manager_sees_direction_cases_enabled", "manager_can_take_colleague_dialog_enabled",
            "reassign_moves_tasks_enabled", "admin_kg_entry_enabled", "kg_entry_enabled",
            "kg_entry_manager_access_enabled", "auto_close_after_touches_enabled",
            "followup_enabled", "kg_entry_fees_reply_enabled", "visa_usa_business_price_enabled"]
for f in PROD_ON:
    assert hasattr(s, f), f
    setattr(s, f, True)
for f in PROD_OFF:
    if hasattr(s, f):
        setattr(s, f, False)

# --- 3. Планировщик не запускаем, отправка «понарошку» ---------------------------------
from app.core import scheduler
scheduler.start = lambda: None

from app.channels import outbound
from app.channels import wappi

_fake_n = [0]


def _fake_id():
    _fake_n[0] += 1
    return f"stand-{_fake_n[0]}"


async def _fake_send_to_client(*a, **k):
    return _fake_id()


async def _fake_wappi_send(self, *a, **k):
    return _fake_id()


outbound.send_to_client = _fake_send_to_client
wappi.WappiAdapter.send = _fake_wappi_send
wappi.WappiAdapter.send_file = _fake_wappi_send

# --- 4. Доменная база на SQLite -----------------------------------------------------------
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.integrations.crm import db as crm_db
from app.domain.models import DomainBase

engine = create_async_engine(s.database_url, poolclass=NullPool)


async def _schema():
    async with engine.begin() as conn:
        await conn.run_sync(crm_db.Base.metadata.create_all)
        await conn.run_sync(DomainBase.metadata.create_all)


asyncio.run(_schema())
crm_db._engine = engine
crm_db._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

import app.main as main  # noqa: E402
from app.integrations.panel import store as ps  # noqa: E402
from app.integrations.panel.store import ConversationView, MessageView  # noqa: E402

# --- 5. Вымышленные клиенты ------------------------------------------------------------------
NOW = datetime.now(timezone.utc)
# id сообщений засева — с большого числа: у хранилища в памяти свой счётчик с 1,
# и пересечение id ломало бы статус «отправлено» у новых сообщений менеджера.
_mid = [500000]


def _msgs(script, last_at, step_min=3):
    out = []
    n = len(script)
    for k, (sender, text) in enumerate(script):
        _mid[0] += 1
        at = last_at - timedelta(minutes=(n - 1 - k) * step_min)
        out.append(MessageView(sender=sender, text=text, created_at=at, id=_mid[0],
                               status="" if sender == "client" else "sent"))
    return out


def add(bot, funnel, phone, name, stage, ago_min, script, *, assigned="", intercepted=False,
        summary="", next_step="", step_min=3, **extra):
    uid = f"{bot}:{phone}"
    last = NOW - timedelta(minutes=ago_min)
    msgs = _msgs(script, last, step_min)
    cv = ConversationView(user_id=uid, phone=phone, channel="whatsapp", chat_id=phone,
                          bot_id=bot, funnel=funnel, stage=stage, last_message_at=last,
                          last_sender=msgs[-1].sender, last_text=msgs[-1].text[:120],
                          qualification={"name": name} if name else {},
                          assigned_to=assigned, intercepted=intercepted,
                          ai_summary=summary, manager_next_step=next_step, **extra)
    cv.messages = msgs
    ps._memory_store._conv[uid] = cv
    return uid


V, T = "getvisa", "frunze_tours"
# --- визы: главные герои скриншотов
add(V, "visa", "996700000101", "Айгерим Т.", "greeting", 4, [
    ("client", "Здравствуйте! Сколько стоит виза в США?"),
    ("bot", "Здравствуйте, Айгерим! Консультация и подготовка документов на визу США — 250$. "
            "Подскажите, какая цель поездки: туризм или работа?"),
    ("client", "Туризм, хочу в мае. А можно прийти в офис в субботу?"),
], summary="США, туризм, май. Хочет прийти в офис в субботу.",
   next_step="Записать на консультацию в субботу")
add(V, "visa", "996700000102", "Нурлан К.", "qualification", 18, [
    ("client", "Добрый день, нужна шенгенская виза в Германию"),
    ("bot", "Добрый день! Подскажите, пожалуйста, вы работаете официально? Были ли отказы?"),
    ("client", "Работаю ИП, отказов не было. Какие документы нужны?"),
])
add(V, "visa", "996700000103", "Бакыт С.", "progress", 47, [
    ("client", "Салам! Виза в Великобританию для двоих"),
    ("bot", "Здравствуйте! Консультация 100€ на человека. Когда планируете поездку?"),
    ("client", "В июле. Можно записаться на консультацию?"),
])
add(V, "visa", "996700000104", "Жылдыз А.", "office", 130, [
    ("client", "Здравствуйте, хочу визу в Японию"),
    ("bot", "Здравствуйте! Записала вас в офис на пятницу, 11:00. Адрес отправлю ниже."),
    ("client", "Спасибо, приду"),
], assigned="medina", intercepted=True)
add(V, "visa", "996700000105", "Эрмек Д.", "follow_up", 60 * 26, [
    ("client", "Сколько стоит виза в Корею?"),
    ("manager", "Здравствуйте! Консультация 80$. Пришлите, пожалуйста, фото паспорта."),
], assigned="medina", intercepted=True)
add(V, "visa", "996700000106", "Салтанат М.", "follow_up", 60 * 24 * 4, [
    ("client", "Нужна виза в Канаду для дочери"),
    ("manager", "Добрый день! Для Канады нужны справка с работы и выписка из банка. "
                "Когда сможете принести?"),
], assigned="medina", intercepted=True)
add(V, "visa", "996700000107", "Тимур Б.", "qualification", 60 * 5, [
    ("client", "Виза в Китай нужна срочно"),
    ("manager", "Здравствуйте! Срочное оформление — 5 рабочих дней. Подскажите даты поездки."),
    ("client", "Вылет 20 декабря"),
], assigned="medina", intercepted=True)
add(V, "visa", "996700000108", "Динара Ж.", "silent", 60 * 30, [
    ("client", "Здравствуйте, сколько стоит Шенген?"),
    ("bot", "Здравствуйте! Консультация 100€. Подскажите, в какую страну планируете поездку?"),
])
add(V, "visa", "996700000109", "Азамат Р.", "greeting", 9, [
    ("client", "Здравствуйте, есть ли у вас виза в ОАЭ?"),
])
add(V, "visa", "996700000110", "Гульнара Э.", "manager", 60 * 3, [
    ("client", "Мне отказали в визе США, можно ещё раз подать?"),
    ("bot", "Понимаю вас. Передаю ваш вопрос менеджеру, она свяжется с вами в течение часа."),
], next_step="Повторная подача США после отказа — позвонить")
# --- визы: массовка для колонки «Новый лид» (проверка «Ещё N · показать все»)
FIRST = ["Асель", "Бекзат", "Чолпон", "Данияр", "Элнура", "Мирлан", "Айпери", "Улан", "Нуриза",
         "Канат", "Айжан", "Эльдар", "Мээрим", "Руслан", "Самара", "Таалай"]
QUESTIONS = ["Сколько стоит виза в США?", "Какие документы нужны на Шенген?",
             "Можно записаться на консультацию?", "Виза в Корею сколько дней делается?",
             "Здравствуйте, нужна виза в Англию", "Подскажите по визе в Японию"]
for i in range(64):
    name = f"{FIRST[i % len(FIRST)]} {chr(0x410 + (i * 7) % 28)}."
    ago = 60 * 24 * (2 + i % 25) + i * 13
    script = [("client", QUESTIONS[i % len(QUESTIONS)]),
              ("bot", "Здравствуйте! Подскажите, как вас зовут и куда планируете поездку?")]
    # followup_count=2: дожим исчерпан, поэтому лид остаётся в «Новый лид», а не уходит в «Молчат».
    add(V, "visa", f"996700001{i:03d}", name, "greeting", ago, script, followup_count=2)

# --- туры: для раздела Даулета
add(T, "tours", "996700000201", "Айбек Н.", "greeting", 6, [
    ("client", "Здравствуйте! Тур в Турцию на двоих в январе, сколько стоит?"),
    ("bot", "Здравствуйте! Подскажите, пожалуйста, даты вылета и бюджет?"),
    ("client", "С 10 января на 7 ночей, до 1500$"),
])
add(T, "tours", "996700000202", "Камила У.", "qualification", 35, [
    ("client", "Дубай на новогодние, есть варианты?"),
    ("bot", "Здравствуйте! Сколько взрослых и детей поедут? Возраст детей подскажите."),
    ("client", "Двое взрослых и ребёнок 6 лет"),
])
add(T, "tours", "996700000203", "Эрлан Т.", "progress", 90, [
    ("client", "Хотим на Мальдивы в феврале"),
    ("bot", "Подобрала 3 варианта, отправляю подборку. Какой нравится больше?"),
])
add(T, "tours", "996700000204", "Венера С.", "office", 60 * 6, [
    ("client", "Давайте забронируем Анталью"),
    ("manager", "Отлично! Ждём вас в офисе завтра в 12:00 с паспортами."),
], assigned="daulet", intercepted=True)
add(T, "tours", "996700000205", "Максат О.", "silent", 60 * 50, [
    ("client", "Баку на 4 дня сколько?"),
    ("bot", "Здравствуйте! Подскажите, пожалуйста, даты и сколько человек?"),
])
add(T, "tours", "996700000206", "Алия Б.", "manager", 25, [
    ("client", "Можно в рассрочку оплатить тур?"),
    ("bot", "Передаю ваш вопрос менеджеру — он ответит в ближайшее время."),
])
print("seeded", len(ps._memory_store._conv), "conversations")


# --- 6. Касания: настоящая джоба создаёт задачи-напоминания Медине --------------------------
async def _touches():
    from app.core import touches
    return await touches.run(NOW)


print("touch tasks created:", asyncio.run(_touches()))


async def _extra_task():
    """Одна обычная задача «позвонить», созданная менеджером вручную (для показа календаря)."""
    from app.domain.calendar_tasks import CalendarTaskService, bishkek_today
    from app.domain.services import ContactService
    async with crm_db._sessionmaker() as session:
        contact = await ContactService.find_or_create_by_identity(
            session, "phone", "996700000107", assume_e164=True)
        await CalendarTaskService.create(
            session, manager_id="medina", direction="visa", kind="call",
            scheduled_date=bishkek_today(NOW), scheduled_at=None, contact_id=contact.id,
            user_id="getvisa:996700000107", priority="high", created_by="medina",
            comment="Перезвонить Тимуру: уточнить даты вылета в Китай")
        await session.commit()


asyncio.run(_extra_task())

# --- 7. Сервер ----------------------------------------------------------------------------------
import uvicorn  # noqa: E402

srv = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=PORT, log_level="warning"))
print(f"stand: http://127.0.0.1:{PORT}/admin/login  (medina / daulet / marsel / grisha-admin, пароль demo)")
srv.run()
