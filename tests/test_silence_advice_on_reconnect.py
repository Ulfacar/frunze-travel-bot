"""Сторож тишины не советует QR, когда профиль просто переподключается.

Продолжение гейта `tests/test_silence_advice_respects_profile_health.py` (01.09.2026), который
исполнителем не редактируется: там закрыт случай «профиль здоров», здесь — «профиль
авторизован, но приложение переподключается».

Замер 27.09.2026: серия `app_status=connecting` держалась 11:56–13:00 (64 минуты) синхронно
по трём профилям при `authorized=true` во всех записях, и канал `frunze_tours_sezim` в эти же
минуты принимал от клиентов голосовые и документы. Значит переподключение — не разлогин, и
советовать по нему QR значит отправлять владельца чинить работающее.

Задача: ai/tasks/2026-09-29-qr-advice-on-reconnect.md
"""
from __future__ import annotations

from app.core import channel_heartbeat as hb
from app.core import wappi_health as wh


def _status(**over) -> dict:
    base = {
        "app_status": "open",
        "authorized": True,
        "authorized_at": "2026-09-27T01:41:02.209481+03:00",
        "payment_expired_at": "2026-12-20T00:00:00Z",
        "profile_id": "02a4708d-ec6c",
    }
    base.update(over)
    return base


# ---------- чистая функция состояния ----------

def test_condition_tells_reconnect_from_logout():
    """Две разные беды, которые раньше сливались в одно «нездоров»."""
    assert wh.profile_condition(_status()) == "ok"
    assert wh.profile_condition(_status(app_status="connecting")) == wh.RECONNECTING
    assert wh.profile_condition(_status(app_status="close")) == wh.RECONNECTING
    assert wh.profile_condition(_status(authorized=False, app_status="close")) == "logged_out"
    assert wh.profile_condition(_status(authorized=False, app_status="open")) == "logged_out"


def test_condition_says_nothing_when_wappi_did_not_answer():
    """Wappi не ответил — состояние неизвестно. Врать в любую сторону нельзя."""
    assert wh.profile_condition(None) is None
    assert wh.profile_condition("") is None
    assert wh.profile_condition(["не словарь"]) is None


def test_condition_survives_garbage_fields():
    """Мусор в ответе не выглядит ни здоровьем, ни переподключением.

    Поправлено по находке независимого ревью 29.09: раньше ответ без `app_status` давал
    «переподключается», то есть мусор превращался в утверждение о состоянии канала.
    Нет поля — нет вывода, и владелец получает прежний нейтральный текст.
    """
    assert wh.profile_condition({}) is None                       # пустой ответ — не разлогин
    assert wh.profile_condition({"authorized": True}) is None     # app_status потерян
    assert wh.profile_condition({"authorized": True, "app_status": None}) is None
    assert wh.profile_condition({"authorized": True, "app_status": ""}) is None


# ---------- текст совета ----------

def test_reconnecting_advice_never_orders_a_qr_scan():
    """AC1: авторизация жива → инструкции сканировать QR нет.

    Слово «QR» в тексте допустимо и даже полезно — ровно чтобы отменить ложный вывод
    («QR сканировать не нужно»), так же как в гейте 01.09 для здорового профиля. Запрещено
    другое: требование проверить авторизацию, которое отправляет владельца в кабинет Wappi.
    """
    text = hb._text("getvisa", 18 * 60, diagnosis="", healthy=wh.RECONNECTING).lower()

    assert "не нужно" in text
    assert "проверь авторизацию" not in text
    assert "переподключается" in text


def test_reconnecting_advice_still_points_somewhere_useful():
    """Совет обязан сказать, куда смотреть, а не только чего не делать."""
    text = hb._text("getvisa", 18 * 60, diagnosis="", healthy=wh.RECONNECTING).lower()

    assert "вебхук" in text


def test_real_logout_keeps_the_qr_advice():
    """AC2: слетевшая авторизация — это ровно тот случай, ради которого совет существует."""
    text = hb._text("getvisa", 18 * 60, diagnosis="", healthy=False).lower()

    assert "qr" in text


def test_gate_cases_are_untouched():
    """AC4: три случая гейта 01.09 ведут себя ровно как прежде."""
    healthy = hb._text("getvisa", 18 * 60, diagnosis="", healthy=True).lower()
    unknown = hb._text("getvisa", 18 * 60, diagnosis="", healthy=None).lower()

    assert "qr" in healthy and "не нужно" in healthy      # здоров: QR прямо отменён
    assert "qr" in unknown                                # неизвестно: прежний нейтральный текст


def test_traffic_diagnosis_still_wins_over_health():
    """Диагноз трафика конкретнее здоровья профиля и остаётся приоритетным."""
    for diagnosis in ("webhook", "no_traffic"):
        text = hb._text("getvisa", 18 * 60, diagnosis=diagnosis,
                        healthy=wh.RECONNECTING).lower()
        assert "переподключается" not in text


# ---------- находки независимого ревью 29.09 ----------

def test_log_line_survives_the_reconnecting_state():
    """BLOCKER обоих ревьюеров: словарь брался через [] и падал KeyError.

    Падение происходило ПОСЛЕ записи защёлки cooldown, поэтому канал остался бы без алерта
    на сутки, а исключение обрывало цикл и лишало алертов остальные каналы.
    """
    line = hb.down_log_line("getvisa", 720, diagnosis="", healthy=wh.RECONNECTING)

    assert "переподключается" in line
    assert "getvisa" in line


def test_log_line_never_raises_on_an_unknown_state():
    """Следующее новое состояние не должно ронять джобу — это тот же дефект второй раз."""
    for value in (wh.RECONNECTING, True, False, None, "что-то новое", 0, 1):
        assert "CHANNEL DOWN" in hb.down_log_line("getvisa", 60, healthy=value)


def test_flag_registered_in_admin_panel():
    """Откат тумблером обещан в карточке задачи — значит тумблер обязан существовать."""
    from app.admin.router import FEATURE_FLAGS

    assert "wappi_reconnecting_advice_enabled" in FEATURE_FLAGS
    entry = FEATURE_FLAGS["wappi_reconnecting_advice_enabled"]
    assert entry["title"] and entry["desc"]
    assert entry["default"]() is False          # дефолт OFF, как требует протокол


def test_advice_says_when_to_stop_waiting():
    """Ложное успокоение ограничено: текст говорит, через сколько считать канал потерянным.

    `authorized=true` держится по семантике сессии даже при выключенном телефоне, поэтому
    обещать «всё в порядке» бессрочно нельзя.
    """
    text = hb._text("getvisa", 18 * 60, diagnosis="", healthy=wh.RECONNECTING).lower()

    assert "полутора часов" in text or "90" in text
    assert "потерянным" in text


def test_non_boolean_authorization_is_never_read_as_authorized():
    """Находка финального аудита 29.09: строка «false» истинна в Python.

    На таком ответе разлогин выглядел бы переподключением, а совет сказал бы «QR не нужен» —
    ровно тогда, когда QR и нужен. Чужой формат означает «не знаю», а не «всё хорошо».
    """
    assert wh.profile_condition({"authorized": "false", "app_status": "connecting"}) is None
    assert wh.profile_condition({"authorized": "true", "app_status": "connecting"}) is None
    assert wh.profile_condition({"authorized": 1, "app_status": "open"}) is None
    assert wh.profile_condition({"authorized": None, "app_status": "open"}) is None
    # настоящие булевы значения по-прежнему работают
    assert wh.profile_condition({"authorized": True, "app_status": "connecting"}) == wh.RECONNECTING
    assert wh.profile_condition({"authorized": False, "app_status": "connecting"}) == "logged_out"
