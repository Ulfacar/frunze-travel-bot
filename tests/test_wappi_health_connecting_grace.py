"""Грация на переподключение Wappi: `connecting`/`close` при живой авторизации — не разлогин.

Почему добавлено отдельным файлом: `tests/test_wappi_health.py` — гейт задачи v3, он
помечен «исполнителем НЕ редактируется». Его ожидания при флаге OFF сохраняются целиком.

Замер, из которого взят порог (логи прода 27.09.2026 + `messages`):
серия нездоровых проб держалась 11:56–13:00 (64 минуты) синхронно по трём профилям,
`authorized=true` во ВСЕХ записях, статус — `connecting`, к концу серии `close`.
Сторож отправил три тревоги «сканируйте QR» в 12:07. При этом канал `frunze_tours_sezim`
в 09:12–10:16 UTC (те же минуты) принимал от клиентов голосовые и документы и отдавал
ответы менеджера — то есть канал был жив, а тревога ложна.

Прогон настоящей `decide()` по этому ряду: грация 30/45 мин — те же 3 тревоги (лишь позже),
60 мин — 1, **90 мин — 0**. Настоящий разлогин (`authorized=false`) ловится при любой грации.
"""
from __future__ import annotations

NOW = 1_000_000.0
TICK = 330.0          # фактический шаг проб на проде (планировщик тикает раз в 300 с)


class Cfg:
    """Прод-настройки на день замера + включённая грация."""
    wappi_health_enabled = True
    wappi_health_cooldown_minutes = 1440
    wappi_health_confirm_ticks = 3
    wappi_payment_warn_days = 7
    wappi_connecting_grace_enabled = True
    wappi_connecting_grace_minutes = 90


class CfgOff(Cfg):
    wappi_connecting_grace_enabled = False


def _status(**over) -> dict:
    base = {
        "app_status": "open",
        "authorized": True,
        "authorized_at": "2026-09-27T01:41:02.209481+03:00",
        "payment_expired_at": "2026-12-20T00:00:00Z",
        "name": "FrunzeTravel2",
        "profile_id": "02a4708d-ec6c",
    }
    base.update(over)
    return base


def _ids(alerts) -> list[str]:
    return [bot_id for bot_id, _ in alerts]


def _run_series(cfg, status: dict, ticks: int, start: float = NOW) -> list[str]:
    """Прогнать подряд `ticks` одинаковых проб. Вернуть, по каким каналам были тревоги."""
    from app.core.wappi_health import decide

    state: dict = {}
    fired: list[str] = []
    for i in range(ticks):
        fired += _ids(decide(start + i * TICK, {"frunze_tours": status}, state, cfg))
    return fired


def test_connecting_within_grace_stays_silent():
    """64-минутная серия `connecting` (реальная, 27.09) при грации 90 мин — ни одной тревоги."""
    assert _run_series(Cfg(), _status(app_status="connecting"), ticks=12) == []


def test_closed_app_within_grace_stays_silent_too():
    """К концу серии Wappi отдавал `close`, авторизация оставалась живой — тоже переподключение."""
    assert _run_series(Cfg(), _status(app_status="close"), ticks=12) == []


def test_connecting_longer_than_grace_alerts():
    """Грация — отсрочка, а не глухота: висит дольше порога → тревога всё равно приходит."""
    fired = _run_series(Cfg(), _status(app_status="connecting"), ticks=24)

    assert fired == ["frunze_tours"]          # одна: дальше держит cooldown


def test_lost_authorization_alerts_immediately_despite_grace():
    """authorized=false — тот самый разлогин 03.08: грации не даём, ловим по confirm_ticks."""
    fired = _run_series(Cfg(), _status(authorized=False, app_status="close"), ticks=6)

    assert fired == ["frunze_tours"]


def test_flag_off_keeps_old_behaviour():
    """Флаг OFF — поведение ровно прежнее: три нездоровые пробы и тревога, как 27.09."""
    fired = _run_series(CfgOff(), _status(app_status="connecting"), ticks=12)

    assert fired == ["frunze_tours"]


def test_single_healthy_blip_does_not_restart_grace():
    """Находка ревью класса C, подтверждённая данными: одна здоровая проба НЕ снимает окно.

    27.09 в середине 64-минутной серии у frunze_tours проба 12:47 вышла здоровой, а в 12:55
    канал упал снова. Если окно сбрасывать по одной пробе, канал, моргающий чаще раза в
    грацию, не дождётся тревоги никогда — отсчёт каждый раз начинался бы с нуля.
    """
    from app.core.wappi_health import decide

    state: dict = {}
    bad, good = _status(app_status="connecting"), _status()
    cfg = Cfg()
    fired: list[str] = []
    t = NOW
    # 80 минут болезни (внутри грации 90) — молчим
    for _ in range(15):
        fired += _ids(decide(t, {"frunze_tours": bad}, state, cfg))
        t += TICK
    assert fired == []
    # одна здоровая проба — это ещё не выздоровление
    fired += _ids(decide(t, {"frunze_tours": good}, state, cfg))
    t += TICK
    # ещё 20 минут болезни: суммарно окно 90 минут истекло → тревога приходит
    for _ in range(4):
        fired += _ids(decide(t, {"frunze_tours": bad}, state, cfg))
        t += TICK

    assert fired == ["frunze_tours"]


def test_confirm_healthy_probes_close_the_incident():
    """`confirm` здоровых проб подряд = канал вернулся: следующая авария считается заново."""
    from app.core.wappi_health import decide

    state: dict = {}
    bad, good = _status(app_status="connecting"), _status()
    cfg = Cfg()
    fired: list[str] = []
    t = NOW
    for _ in range(15):                      # 80 минут болезни, внутри грации
        fired += _ids(decide(t, {"frunze_tours": bad}, state, cfg))
        t += TICK
    for _ in range(3):                       # три здоровых пробы подряд = выздоровел
        fired += _ids(decide(t, {"frunze_tours": good}, state, cfg))
        t += TICK
    for _ in range(15):                      # новая серия 80 минут — снова внутри грации
        fired += _ids(decide(t, {"frunze_tours": bad}, state, cfg))
        t += TICK

    assert fired == []


def test_payment_warning_survives_grace():
    """Грация трогает только повод «разлогин». Про оплату сторож обязан сказать всё равно.

    На 27.09 это и были законные тревоги: подписка туровых профилей истекала 01.10.
    """
    from app.core.wappi_health import decide

    status = _status(app_status="connecting",
                     payment_expired_at="2026-10-01T00:00:00Z")
    now = 1_790_560_800.0        # 28.09.2026 02:00 UTC — трое суток до конца подписки
    alerts = decide(now, {"frunze_tours": status}, {}, Cfg())

    assert _ids(alerts) == ["frunze_tours"]
    assert "оплат" in alerts[0][1].lower() or "подписк" in alerts[0][1].lower()
