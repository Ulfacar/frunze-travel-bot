"""ГЕЙТ: уведомление о канале должно ставить ДИАГНОЗ, а не давать один совет на всё.

Написан ДО реализации. Гейты v1/v2/v3/v3.1 не редактируются.

09.08 владелец показал четыре реальных уведомления. Два из них дали неверный совет:

    [07.08 12:54] 🔴 Канал getvisa (Медина) отвалился: приложение в состоянии
                  «connecting». Нужно заново отсканировать QR в профиле Wappi.
    [08.08 06:42] 🔴 Канал frunze_tours_sezim (Айсина) молчит 12 ч — входящих нет.
                  Проверь профиль в Wappi: авторизация (QR) и адрес вебхука.

В первом профиль был АВТОРИЗОВАН и просто переподключался — сканировать QR не требовалось.
Во втором авторизация и вебхук были в порядке: на номер Айсины просто перестали писать
(новые диалоги 13 → 4 → 8 → 3 → 1 → 0 при ровных 9-19 у Адеми и 27-34 у Медины).
Собственный счётчик Wappi по этому профилю вырос за 19 часов всего на 9 — значит
сообщения не терялись по дороге, их не было.

Совет «проверь QR и вебхук» в обоих случаях уводил в сторону от настоящей причины.

Различить эти случаи можно точно, и данные для этого уже приходят в том же ответе Wappi:

    счётчик вырос, а до нас не дошло  → сообщения теряются по дороге (вебхук)
    счётчик тоже стоит                → на номер никто не пишет (реклама, сам номер)
    не авторизован                    → нужен QR, и ТОЛЬКО здесь
    app_status переходный             → не авария, наблюдаем

Требуется от реализации:
    app/core/wappi_health.py:  classify_gap(counter_now, counter_prev, our_inbound_moved) -> str
    app/core/channel_heartbeat.py:  _text(..., diagnosis="") подставляет верный совет
"""
from __future__ import annotations

NOW = 1_000_000.0
DAY_HOUR = 14


def _ago(minutes: float) -> float:
    return NOW - minutes * 60


def _ids(alerts) -> list[str]:
    return [bot_id for bot_id, _ in alerts]


# --- различение причин ----------------------------------------------------------

def test_counter_grew_while_we_got_nothing_is_a_webhook_problem():
    from app.core.wappi_health import classify_gap

    assert classify_gap(counter_now=740, counter_prev=715, our_inbound_moved=False) == "webhook"


def test_counter_flat_means_nobody_writes():
    """Случай Айсины: и у нас тихо, и у Wappi тихо."""
    from app.core.wappi_health import classify_gap

    assert classify_gap(counter_now=715, counter_prev=715, our_inbound_moved=False) == "no_traffic"


def test_our_inbound_moved_means_nothing_to_diagnose():
    from app.core.wappi_health import classify_gap

    assert classify_gap(counter_now=740, counter_prev=715, our_inbound_moved=True) == ""


def test_missing_counter_gives_no_verdict():
    """Wappi не ответил — молчим о причине, а не выдумываем её."""
    from app.core.wappi_health import classify_gap

    assert classify_gap(counter_now=None, counter_prev=715, our_inbound_moved=False) == ""
    assert classify_gap(counter_now=715, counter_prev=None, our_inbound_moved=False) == ""


# --- тексты: советы обязаны соответствовать диагнозу ----------------------------

def test_no_traffic_text_does_not_send_anyone_to_scan_qr():
    """Дословно уведомление 08.08 06:42, которое увело в сторону."""
    from app.core.channel_heartbeat import _text

    text = _text("frunze_tours_sezim", 12 * 60, diagnosis="no_traffic").lower()
    assert "qr" not in text
    assert "вебхук" not in text
    assert "реклам" in text or "номер" in text


def test_webhook_text_points_at_the_webhook():
    from app.core.channel_heartbeat import _text

    text = _text("getvisa", 12 * 60, diagnosis="webhook").lower()
    assert "вебхук" in text
    assert "qr" not in text


def test_unknown_diagnosis_keeps_the_neutral_wording():
    """Без данных о причине — прежний нейтральный текст, без ложной уверенности."""
    from app.core.channel_heartbeat import _text

    text = _text("getvisa", 12 * 60).lower()
    assert "входящих нет" in text


def test_qr_is_advised_only_when_really_unauthorized():
    from app.core.wappi_health import _logout_text

    unauthorized = _logout_text("getvisa", {"authorized": False, "app_status": "close"})
    assert "qr" in unauthorized.lower()

    # Проверяем не слово «QR», а ИНСТРУКЦИЮ его сканировать: упоминание в отрицании
    # («QR сканировать НЕ нужно») полезно — прошлые уведомления приучили к обратному.
    connecting = _logout_text("getvisa", {"authorized": True, "app_status": "connecting"})
    low = connecting.lower()
    assert "отсканировать qr" not in low and "сканируй qr" not in low
    assert "не нужно" in low or "незачем" in low


def test_the_exact_misleading_message_is_no_longer_produced():
    """Уведомление 07.08 12:54 дословно: «отвалился… отсканировать QR» при authorized=true."""
    from app.core.wappi_health import _logout_text

    text = _logout_text("getvisa", {"authorized": True, "app_status": "connecting"})
    assert "отсканировать qr" not in text.lower()
    assert "connecting" in text.lower()


def test_transient_state_reads_as_observation_not_disaster():
    from app.core.wappi_health import _logout_text

    text = _logout_text("getvisa", {"authorized": True, "app_status": "connecting"})
    assert "переподключ" in text.lower() or "связь" in text.lower()


# --- диагноз доезжает до самого алерта ------------------------------------------

def test_decide_passes_diagnosis_into_the_alert():
    from app.config import settings
    from app.core.channel_heartbeat import decide

    alerts = decide(NOW, {"frunze_tours_sezim": _ago(13 * 60)}, {}, settings,
                    bishkek_hour=DAY_HOUR, diagnoses={"frunze_tours_sezim": "no_traffic"})
    assert _ids(alerts) == ["frunze_tours_sezim"]
    assert "qr" not in alerts[0][1].lower()


def test_diagnoses_default_to_empty_and_change_nothing():
    from app.config import settings
    from app.core.channel_heartbeat import decide

    alerts = decide(NOW, {"getvisa": _ago(13 * 60)}, {}, settings, bishkek_hour=DAY_HOUR)
    assert _ids(alerts) == ["getvisa"]
