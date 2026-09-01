"""ГЕЙТ: сторож тишины не советует QR по каналу, который Wappi считает живым.

Написан ДО реализации и исполнителем НЕ редактируется.

## Замер, из которого выросла задача (прод, 01.09.2026)

01.09 в 11:45 по Бишкеку владельцу ушло:

    🔴 Канал getvisa (Медина) молчит 12 ч — входящих нет.
    Проверь профиль в Wappi: авторизация (QR) и адрес вебхука.

В ту же минуту Wappi по этому профилю отвечал `authorized=true, app_status=open`,
подписка оплачена до 20.09, а за всё окно логов (с 24.08) нет ни одной записи
«проба нездорова» — то есть профиль ни разу не был разлогинен. Совет сканировать QR
был ложным, и владелец пошёл проверять то, что и так работало.

Механика дефекта: `_advice()` выбирает совет ТОЛЬКО по диагнозу трафика. Когда диагноз
неизвестен (счётчик Wappi не пришёл), срабатывает фолбэк со словами «авторизация (QR)».
При этом факт «профиль авторизован и open» у нас уже есть — `wappi_health` опрашивает
статус каждые пять минут, — но до текста алерта он не доезжает. Два сторожа делятся
ровно одним сигналом («про разлогин уже сказано») и не делятся здоровьем профиля.

## Правило

Инструкция сканировать QR звучит только тогда, когда Wappi сам сказал, что с профилем
что-то не так. Здоровый профиль (`authorized=true`, `app_status=open`) её отменяет:
QR тут ни при чём, и говорить обратное — уводить в сторону.

Неизвестное здоровье (Wappi не ответил) сохраняет прежний нейтральный текст: врать
про здоровье в другую сторону мы тоже не имеем права.

Будить при неизвестном диагнозе продолжаем — это правило гейта
`test_silence_alert_only_on_gap.py` и оно не отменяется, меняется только СОВЕТ.
"""
from __future__ import annotations

from app.core import channel_heartbeat as hb

HOUR = 3600.0
NOW = 1_788_241_536.0        # 01.09.2026 05:45 UTC — минута того самого уведомления
DAY_HOUR = 11                # 11:45 по Бишкеку


class Cfg:
    channel_heartbeat_enabled = True
    channel_silence_minutes = 720
    channel_silence_night_minutes = 720
    channel_alert_cooldown_minutes = 1440
    silence_alert_only_on_gap = True


def _silent(hours=18.0):
    return {"getvisa": NOW - hours * HOUR}


def _ids(alerts):
    return [bot_id for bot_id, _ in alerts]


# ---------------- совет по здоровому профилю --------------------------------------
def test_healthy_profile_never_advises_scanning_qr():
    """Дословный случай 01.09: диагноза нет, профиль жив — QR не предлагаем.

    Проверяем не слово «QR», а ИНСТРУКЦИЮ его сканировать: упоминание в отрицании
    («QR сканировать не нужно») полезно — прошлые уведомления приучили к обратному.
    """
    text = hb._text("getvisa", 18 * 60, diagnosis="", healthy=True).lower()
    assert "отсканир" not in text and "сканируй qr" not in text
    assert "авторизован" in text
    assert "не нужно" in text or "ни при чём" in text


def test_healthy_profile_points_where_it_is_worth_looking():
    """Профиль жив, а входящих нет — единственное, что осталось проверить, это вебхук."""
    text = hb._text("getvisa", 18 * 60, diagnosis="", healthy=True).lower()
    assert "вебхук" in text


def test_unhealthy_profile_keeps_the_qr_advice():
    """Wappi сказал, что с профилем плохо — вот тут QR как раз по делу."""
    text = hb._text("getvisa", 18 * 60, diagnosis="", healthy=False).lower()
    assert "qr" in text


def test_unknown_health_keeps_the_previous_neutral_wording():
    """Wappi не ответил — прежний текст, без новой уверенности в любую сторону."""
    assert hb._text("getvisa", 18 * 60, diagnosis="") == \
        hb._text("getvisa", 18 * 60, diagnosis="", healthy=None)


def test_precise_diagnoses_are_untouched_by_health():
    """Точный диагноз уже даёт точный совет — здоровье его не переписывает."""
    for diagnosis, must_have in (("webhook", "вебхук"), ("no_traffic", "не в технике")):
        text = hb._text("getvisa", 18 * 60, diagnosis=diagnosis, healthy=True).lower()
        assert must_have in text
        assert "отсканир" not in text


# ---------------- здоровье доезжает от decide до текста ----------------------------
def test_decide_passes_health_into_the_alert():
    alerts = hb.decide(NOW, _silent(), {}, Cfg, bishkek_hour=DAY_HOUR,
                       diagnoses={}, healthy={"getvisa": True})
    assert _ids(alerts) == ["getvisa"], "неизвестный диагноз по-прежнему будит"
    assert "отсканир" not in alerts[0][1].lower()
    assert "авторизован" in alerts[0][1].lower()


def test_decide_without_health_behaves_exactly_as_before():
    """Ложноположительный: новый параметр по умолчанию ничего не меняет."""
    assert hb.decide(NOW, _silent(), {}, Cfg, bishkek_hour=DAY_HOUR, diagnoses={}) == \
        hb.decide(NOW, _silent(), {}, Cfg, bishkek_hour=DAY_HOUR, diagnoses={}, healthy=None)


def test_health_does_not_silence_a_real_webhook_gap():
    """Ложноположительный: здоровый профиль — не повод промолчать о настоящей поломке."""
    alerts = hb.decide(NOW, _silent(), {}, Cfg, bishkek_hour=DAY_HOUR,
                       diagnoses={"getvisa": "webhook"}, healthy={"getvisa": True})
    assert _ids(alerts) == ["getvisa"]


def test_health_does_not_break_the_no_traffic_mute():
    """Ложноположительный: отсечка «тихо и там, и у нас» продолжает работать."""
    assert hb.decide(NOW, _silent(), {}, Cfg, bishkek_hour=DAY_HOUR,
                     diagnoses={"getvisa": "no_traffic"}, healthy={"getvisa": True}) == []


# ---------------- источник здоровья ------------------------------------------------
def test_wappi_health_reports_diagnoses_and_health_in_one_pass():
    """Здоровье берётся из ТОГО ЖЕ ответа Wappi, что и счётчик: лишних запросов нет."""
    import inspect

    from app.core import wappi_health

    assert hasattr(wappi_health, "diagnoses_and_health")
    assert inspect.iscoroutinefunction(wappi_health.diagnoses_and_health)


def test_profile_health_reads_authorized_and_app_status():
    from app.core.wappi_health import profile_health

    assert profile_health({"authorized": True, "app_status": "open"}) is True
    assert profile_health({"authorized": False, "app_status": "close"}) is False
    assert profile_health({"authorized": True, "app_status": "connecting"}) is False
    assert profile_health(None) is None
    assert profile_health({}) is False


def test_alert_log_line_carries_the_reason():
    """01.09 разбирать было нечем: в логе стояло только «CHANNEL DOWN: getvisa».

    Диагноз и здоровье профиля обязаны быть в той же строке — иначе следующий такой
    случай снова разбирается по скриншоту из Telegram.
    """
    line = hb.down_log_line("getvisa", 18 * 60, diagnosis="", healthy=True)
    assert "getvisa" in line
    assert "диагноз" in line.lower()
    assert "профиль" in line.lower()

    unknown = hb.down_log_line("getvisa", 18 * 60, diagnosis="", healthy=None)
    assert unknown != line, "неизвестное здоровье должно отличаться от здорового"
