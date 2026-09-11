"""ГЕЙТ: менеджер отмечает продажу одним касанием, и цифра доезжает до отчёта.

Написан ДО реализации. Правился ОДИН раз — 10.09 после замера на проде и двух
независимых ревью, которые доказали, что часть первоначального контракта была придумана
неверно. Каждая правка названа поимённо в разделе «Что изменилось и почему» ниже;
ослаблено ничего не было, тестов стало вдвое больше.

## Замер, из которого выросла задача (прод, 10.09.2026)

Цепочка от обращения до отчёта рвётся ровно в одном месте — человеческом:

    клиент написал       → бот завёл лид                       работает
    бот выяснил запрос   → двигает стадию, пишет сводку        работает
    менеджер продал тур  → должен нажать «Оплатил»             НЕ НАЖИМАЕТ
    лид → «Подписан»     → бот создаёт сделку в FrunzeTravel   не доходит
    владелец смотрит     → «Продано: 0, конверсия 0.0%»        не доходит

Кнопка «✅ Оплатил» в панели существует с июля — ей воспользовались 1-3 раза за 90 дней.
Не из-за лени: в момент продажи менеджер в WhatsApp, а не в админке. Владелец пятую
неделю подряд получает сводку со строкой «Продано: 0» при 251 обращении за неделю.

## Почему ссылки, а не кнопки Telegram

Менеджерам пишет `@FrunzeHelper_bot`. Кнопки Telegram требуют вебхука, а вебхук
несовместим с опросом, на котором держится мост Алана. Ставим ссылки: одно касание для
менеджера, ноль риска для связи.

## Правило

1. Спрашиваем только про то, где работа реально шла: была подборка туров или диалог
   доходил до офиса/менеджера. Пустые «здравствуйте» не трогаем.
2. Одно сообщение в сутки на менеджера, не больше пяти диалогов в нём. Список из
   двадцати строк не разбирает никто.
3. Ссылка неугадываемая и подписанная: чужой не отметит продажу за менеджера.
4. Повторное нажатие ничего не портит и второй сделки не создаёт.
5. Ночью не пишем.

## Что изменилось и почему (10.09, после замера и ревью)

* **`outcome` перестал означать «диалог закрыт».** Замер на проде: оркестратор пишет туда
  рабочий авто-статус на каждом ходу, непустой он у 564 туровых диалогов из 794.
  Первоначальная проверка «непусто» дала бы 0 кандидатов вместо 92 и отказ по нажатой
  ссылке. Теперь закрытым считается только человеческий финал `won`/`lost`.
* **Открытие ссылки больше ничего не пишет.** Telegram ходит GET-ом по первой ссылке, чтобы
  построить превью, — и отметил бы «Оплатил» за менеджера в первый же вечер. Действие
  переехало в POST, GET показывает страницу с кнопкой.
* **Появился третий ответ «ещё думает».** Без него промежуточное состояние либо силой
  записывалось бы в «не сложилось» (враньё в отчёте), либо диалог выпадал из опроса
  навсегда.
* **В токене больше нет номера клиента.** Прежний тест «номер не утёк» проходил только
  потому, что номер лежал в base64 и декодировался одной командой; адрес при этом оседает
  в access-логе nginx и в истории браузера на телефоне менеджера.
* **Ссылка привязана к логину менеджера** — иначе в журнале не остаётся следа, кто отметил
  продажу, а это запись в боевой CRM.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import ManagerConfig, settings
from app.core import flags, sale_check
from app.integrations.crm.db import Base, Conversation

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)      # 18:00 по Бишкеку


class Cfg:
    sale_check_enabled = True
    sale_check_max_items = 5
    sale_check_min_age_hours = 12
    sale_check_max_age_days = 14
    sale_check_snooze_days = 3
    sale_check_hour = 18            # час по Бишкеку, когда спрашиваем
    webhook_secret = "test-secret"
    public_base_url = "https://frunzetravel.kg"


class Conv:
    """Минимальный диалог в форме, которую читает отбор."""

    def __init__(self, key, *, hours_ago=24, outcome="", stage="qualification",
                 offer=None, assigned_to="ademi", asked=False, bot="frunze_tours",
                 funnel="tours", snooze_days=None):
        self.user_id = key
        self.phone = key.split(":")[-1]
        self.bot_id = bot
        self.funnel = funnel
        self.stage = stage
        self.outcome = outcome
        self.assigned_to = assigned_to
        self.offer_facts = dict(offer or {})
        self.qualification = {"destination": "Турция", "dates": "октябрь", "tourists": "2"}
        self.last_text = "Хорошо, я подумаю"
        self.last_sender = "client"
        self.last_message_at = NOW - timedelta(hours=hours_ago)
        self.archived = False
        self.sale_check_asked_at = NOW - timedelta(days=1) if asked else None
        self.sale_check_snooze_until = (NOW + timedelta(days=snooze_days)
                                        if snooze_days is not None else None)
        # Своя карточка на диалог. Общая карточка — отдельный случай, его строит
        # `_shared()`, и путать эти две вещи в заготовке нельзя.
        self.bitrix_lead_id = "18" + key[-4:]


def run(coro):
    return asyncio.run(coro)


# ---------------- кого спрашиваем -----------------------------------------------------
def test_dialog_with_offer_is_asked():
    """Была подборка туров — самый явный признак, что работа шла."""
    convs = [Conv("frunze_tours:996700000001", offer={"destination": "Турция"})]
    assert sale_check.select_targets(convs, NOW, Cfg) == convs


def test_dialog_that_reached_manager_is_asked():
    convs = [Conv("frunze_tours:996700000002", stage="manager")]
    assert sale_check.select_targets(convs, NOW, Cfg)


def test_dialog_that_reached_office_is_asked():
    convs = [Conv("frunze_tours:996700000003", stage="office")]
    assert sale_check.select_targets(convs, NOW, Cfg)


def test_empty_greeting_is_not_asked():
    """Ложноположительный: «здравствуйте» без продолжения — не про что спрашивать."""
    assert sale_check.select_targets([Conv("frunze_tours:996700000004", stage="greeting")],
                                     NOW, Cfg) == []


def test_already_marked_is_not_asked_again():
    convs = [Conv("frunze_tours:996700000005", stage="manager", outcome="won"),
             Conv("frunze_tours:996700000006", stage="manager", outcome="lost")]
    assert sale_check.select_targets(convs, NOW, Cfg) == []


@pytest.mark.parametrize("auto", ["in_progress", "manager", "office"])
def test_working_auto_status_does_not_close_the_question(auto):
    """ЗАМЕР ПРОДА 10.09: оркестратор пишет авто-статус в `outcome` на каждом ходу.

    Непустой `outcome` у 564 туровых диалогов из 794 — если считать его отметкой исхода,
    вечерний вопрос не уйдёт вообще никому (было ровно так: 0 кандидатов вместо 92).
    """
    convs = [Conv("frunze_tours:996700000010", stage="manager", outcome=auto)]
    assert sale_check.select_targets(convs, NOW, Cfg) == convs


def test_visa_dialog_is_not_asked():
    """Стадию `manager` ставит и визовая воронка — вопрос про отчёт по турам ей не адресован."""
    convs = [Conv("getvisa:996700000011", stage="manager", funnel="visa")]
    assert sale_check.select_targets(convs, NOW, Cfg) == []


def test_fresh_dialog_is_not_asked():
    """Разговор ещё идёт — спрашивать об исходе рано."""
    assert sale_check.select_targets([Conv("frunze_tours:996700000007", stage="manager",
                                           hours_ago=2)], NOW, Cfg) == []


def test_stale_dialog_is_not_asked():
    """Месячной давности разговор менеджер не помнит — ответ будет наугад."""
    assert sale_check.select_targets([Conv("frunze_tours:996700000012", stage="manager",
                                           hours_ago=24 * 40)], NOW, Cfg) == []


def test_dialog_asked_before_is_not_repeated():
    """Один диалог — один вопрос. Менеджера не дёргают дважды про одно и то же."""
    assert sale_check.select_targets([Conv("frunze_tours:996700000008", stage="manager",
                                           asked=True)], NOW, Cfg) == []


def test_thinking_dialog_returns_after_the_snooze():
    """«Ещё думает» покупает ровно один повторный вопрос — когда отсрочка вышла."""
    waiting = Conv("frunze_tours:996700000013", stage="manager", asked=True, snooze_days=2)
    assert sale_check.select_targets([waiting], NOW, Cfg) == []
    assert sale_check.select_targets([waiting], NOW + timedelta(days=3), Cfg) == [waiting]


def test_limit_per_message():
    convs = [Conv(f"frunze_tours:99670000010{i}", stage="manager") for i in range(12)]
    assert len(sale_check.select_targets(convs, NOW, Cfg)) == Cfg.sale_check_max_items


def test_flag_off_asks_nobody():
    """Ложноположительный, обязан пройти: снятый тумблер = ни одного сообщения."""
    class Off(Cfg):
        sale_check_enabled = False

    assert sale_check.select_targets([Conv("frunze_tours:996700000009", stage="manager")],
                                     NOW, Off) == []


def test_runtime_flag_wins_over_env():
    """Тумблер живёт в БД: включённый в панели работает и при выключенном env.

    Иначе получается «кнопка обещает, код молчит» — дефект, который уже чинили (9117f3d).
    """
    class Off(Cfg):
        sale_check_enabled = False

    convs = [Conv("frunze_tours:996700000014", stage="manager")]
    assert sale_check.select_targets(convs, NOW, Off, enabled=True) == convs


# ---------------- ссылка: подпись и защита от подделки --------------------------------
def test_link_round_trip():
    link = sale_check.make_link("frunze_tours:996700000001", "won", Cfg, "ademi")
    assert link.startswith("https://frunzetravel.kg")
    token = link.rsplit("/", 1)[-1]
    cid, outcome, login = sale_check.verify_token(token, Cfg)
    assert (outcome, login) == ("won", "ademi")
    assert cid == sale_check._cid("frunze_tours:996700000001", Cfg)


def test_tampered_token_is_rejected():
    link = sale_check.make_link("frunze_tours:996700000001", "won", Cfg)
    token = link.rsplit("/", 1)[-1]
    assert sale_check.verify_token(token[:-3] + "xyz", Cfg) is None


def test_token_from_another_secret_is_rejected():
    class Other(Cfg):
        webhook_secret = "another-secret"

    token = sale_check.make_link("frunze_tours:996700000001", "won", Cfg).rsplit("/", 1)[-1]
    assert sale_check.verify_token(token, Other) is None


def test_outcome_cannot_be_swapped_in_the_link():
    """Подмена «не сложилось» на «оплатил» в адресе не должна проходить.

    Подделываем честно: раскрываем тело, меняем исход, подпись оставляем старую.
    """
    token = sale_check.make_link("frunze_tours:996700000001", "lost", Cfg).rsplit("/", 1)[-1]
    body, _, sig = token.partition(".")
    forged_body = sale_check._b64(sale_check._unb64(body).replace("|lost|", "|won|"))
    assert sale_check.verify_token(f"{forged_body}.{sig}", Cfg) is None


def test_no_secret_means_no_links_at_all():
    """Fail closed: пустой `webhook_secret` на проде уже случался (чекпоинт 03.08).

    Подпись на константе из открытого репозитория означала бы, что продажу может отметить
    кто угодно, кто видел исходники, — подделка ровно той цифры, ради которой всё делалось.
    """
    class NoSecret(Cfg):
        webhook_secret = ""

    assert sale_check.make_link("frunze_tours:996700000001", "won", NoSecret) == ""
    good = sale_check.make_link("frunze_tours:996700000001", "won", Cfg).rsplit("/", 1)[-1]
    assert sale_check.verify_token(good, NoSecret) is None


def test_two_dialogs_get_different_links():
    a = sale_check.make_link("frunze_tours:996700000001", "won", Cfg)
    b = sale_check.make_link("frunze_tours:996700000002", "won", Cfg)
    assert a != b


def test_token_does_not_carry_the_phone_even_decoded():
    """Адрес осядет в access-логе nginx и в истории браузера на телефоне менеджера.

    Прежняя версия теста искала номер подстрокой и проходила только потому, что номер
    лежал в base64 и разворачивался одной командой.
    """
    token = sale_check.make_link("frunze_tours:996700004477", "won", Cfg).rsplit("/", 1)[-1]
    body = token.partition(".")[0]
    raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode(errors="ignore")
    assert "996700004477" not in raw
    assert "4477" not in raw


# ---------------- текст сообщения менеджеру -------------------------------------------
def test_message_lists_clients_and_three_links_each():
    convs = [Conv("frunze_tours:996700004477", offer={"destination": "Турция"}),
             Conv("frunze_tours:996700008812", stage="office")]
    text = sale_check.render_message(convs, Cfg, NOW)
    assert "4477" in text and "8812" in text
    assert text.count("https://frunzetravel.kg") == 6      # оплатил / не сложилось / думает
    assert "оплат" in text.lower()


def test_message_shows_the_last_line_of_the_dialog():
    """Замер 10.09: направление заполнено у меньшинства, последняя реплика — у всех."""
    convs = [Conv("frunze_tours:996700004477", stage="manager")]
    text = sale_check.render_message(convs, Cfg, NOW)
    assert "клиент: «Хорошо, я подумаю»" in text     # чужие слова не выдаём за клиентские
    assert "вчера" in text


def test_message_does_not_leak_full_phone():
    """Приватность: в сообщение не уходит номер целиком."""
    convs = [Conv("frunze_tours:996700004477", stage="manager")]
    text = sale_check.render_message(convs, Cfg, NOW)
    assert "996700004477" not in text


# ---------------- применение отметки --------------------------------------------------
def test_apply_marks_outcome_and_converts_lead():
    calls = {}

    async def fake_convert(conv_key, lead_id):
        calls["lead"] = (conv_key, lead_id)

    conv = Conv("frunze_tours:996700000001", stage="manager")
    result = run(sale_check.apply_outcome(conv, "won", convert=fake_convert))
    assert result is True
    assert conv.outcome == "won"
    assert calls["lead"] == ("frunze_tours:996700000001", "18" + "0001")


def test_apply_lost_does_not_touch_the_lead():
    """«Не сложилось» — не повод трогать карточку: «Некачественный» ставит человек."""
    called = []

    async def fake_convert(conv_key, lead_id):
        called.append(conv_key)

    conv = Conv("frunze_tours:996700000002", stage="manager")
    run(sale_check.apply_outcome(conv, "lost", convert=fake_convert))
    assert conv.outcome == "lost"
    assert called == []


def test_second_tap_changes_nothing():
    """Ложноположительный: повторное нажатие идемпотентно, второй сделки нет."""
    calls = []

    async def fake_convert(conv_key, lead_id):
        calls.append(conv_key)

    conv = Conv("frunze_tours:996700000003", stage="manager")
    run(sale_check.apply_outcome(conv, "won", convert=fake_convert))
    second = run(sale_check.apply_outcome(conv, "won", convert=fake_convert))
    assert second is False
    assert len(calls) == 1


def test_working_auto_status_does_not_block_the_tap():
    """Тот же дефект с другой стороны: авто-статус не должен отказывать по нажатой ссылке."""
    conv = Conv("frunze_tours:996700000015", stage="manager", outcome="manager")
    assert run(sale_check.apply_outcome(conv, "won")) is True
    assert conv.outcome == "won"


def test_unknown_outcome_is_refused():
    conv = Conv("frunze_tours:996700000004", stage="manager")
    assert run(sale_check.apply_outcome(conv, "whatever")) is False
    assert conv.outcome == ""


def test_thinking_is_not_an_outcome():
    """«Ещё думает» — это отсрочка вопроса, а не исход. В отчёт такое писать нельзя."""
    conv = Conv("frunze_tours:996700000016", stage="manager")
    assert run(sale_check.apply_outcome(conv, "thinking")) is False
    assert conv.outcome == ""


# ---------------- живой путь: БД, джоба, повторный тик ---------------------------------
async def _store(tmp_path, rows, name="sale.db"):
    from app.integrations.panel.store import PostgresConversationStore

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        session.add_all(rows)
        await session.commit()
    return engine, PostgresConversationStore(sessionmaker=sm)


def _row(user_id="frunze_tours:996700000001", **kw):
    kw.setdefault("phone", user_id.split(":")[-1])
    kw.setdefault("bot_id", "frunze_tours")
    kw.setdefault("funnel", "tours")
    kw.setdefault("stage", "manager")
    kw.setdefault("outcome", "manager")        # рабочий авто-статус, как на проде
    kw.setdefault("assigned_to", "ademi")
    kw.setdefault("last_message_at", NOW - timedelta(hours=24))
    kw.setdefault("bitrix_lead_id", "18" + user_id[-4:])
    kw.setdefault("qualification", {"destination": "Турция", "dates": "октябрь",
                                    "tourists": "2"})
    return Conversation(user_id=user_id, **kw)


def test_asking_is_recorded_and_not_repeated_on_the_next_tick(tmp_path, monkeypatch):
    """ГЛАВНЫЙ живой тест: джоба обязана пройти целиком и не повториться.

    Планировщик тикает каждые 5 минут, целевой час длится 12 тиков. Любое исключение
    после успешной отправки (например, `update_meta` без нужного параметра) означает
    двенадцать одинаковых сообщений менеджеру каждый вечер — молча, потому что
    планировщик исключения глушит.
    """
    from app.integrations.panel import store as store_mod

    sent: list[tuple[str, str]] = []

    async def fake_push(token, chat_id, text, **kwargs):
        sent.append((chat_id, text))
        assert kwargs.get("disable_web_page_preview") is True   # иначе превью отметит само
        return True

    async def scenario():
        flags.reset()
        engine, store = await _store(tmp_path, [_row()])
        monkeypatch.setattr(store_mod, "get_conversation_store", lambda: store)
        monkeypatch.setattr(settings, "managers",
                            [ManagerConfig(login="ademi", password="x",
                                           telegram_chat_id="777")])
        monkeypatch.setattr(settings, "sale_check_enabled", True)
        monkeypatch.setattr(settings, "sale_check_hour", 18)
        monkeypatch.setattr(settings, "webhook_secret", "test-secret")
        monkeypatch.setattr(settings, "public_base_url", "https://frunzetravel.kg")
        monkeypatch.setattr("app.core.calendar_brief._token", lambda: "tg-token")
        monkeypatch.setattr("app.core.calendar_brief._push_telegram", fake_push)

        await sale_check.run(NOW)
        await sale_check.run(NOW + timedelta(minutes=5))   # следующий тик того же часа
        conv = await store.get("frunze_tours:996700000001")
        await engine.dispose()
        return conv

    conv = run(scenario())
    assert len(sent) == 1, f"менеджеру ушло {len(sent)} сообщений вместо одного"
    assert conv.sale_check_asked_at is not None, "отметка «спросили» не сохранилась"


def test_only_the_pilot_manager_is_asked(tmp_path, monkeypatch):
    """Класс C обкатывается на одном человеке — механически, а не «повезло».

    На проде 10.09 телеграм есть у пятерых, включая визовых менеджеров и заказчика.
    Тумблер один на всех, поэтому список получателей задаётся явно.
    """
    from app.integrations.panel import store as store_mod

    sent: list[str] = []

    async def fake_push(token, chat_id, text, **kwargs):
        sent.append(chat_id)
        return True

    async def scenario():
        flags.reset()
        engine, store = await _store(
            tmp_path,
            [_row(), _row("frunze_tours:996700000002", assigned_to="aisina")],
            name="pilot.db")
        monkeypatch.setattr(store_mod, "get_conversation_store", lambda: store)
        monkeypatch.setattr(settings, "managers", [
            ManagerConfig(login="ademi", password="x", telegram_chat_id="111"),
            ManagerConfig(login="aisina", password="x", telegram_chat_id="222"),
        ])
        monkeypatch.setattr(settings, "sale_check_managers", ["ademi"])
        monkeypatch.setattr(settings, "sale_check_enabled", True)
        monkeypatch.setattr(settings, "sale_check_hour", 18)
        monkeypatch.setattr(settings, "webhook_secret", "test-secret")
        monkeypatch.setattr(settings, "public_base_url", "https://frunzetravel.kg")
        monkeypatch.setattr("app.core.calendar_brief._token", lambda: "tg-token")
        monkeypatch.setattr("app.core.calendar_brief._push_telegram", fake_push)
        await sale_check.run(NOW)
        await engine.dispose()

    run(scenario())
    assert sent == ["111"], f"вопрос ушёл не только пилоту: {sent}"


def test_tap_writes_outcome_and_survives_a_double_click(tmp_path, monkeypatch):
    """Два тапа подряд — одна запись в БД и ровно один поход в портал."""
    from app.integrations.panel import store as store_mod

    portal: list[str] = []

    async def fake_convert(conv_key, lead_id, *, conv=None):
        portal.append(lead_id)

    async def scenario():
        engine, store = await _store(tmp_path, [_row()], name="tap.db")
        monkeypatch.setattr(store_mod, "get_conversation_store", lambda: store)
        monkeypatch.setattr(sale_check, "_convert_lead", fake_convert)
        cid = sale_check._cid("frunze_tours:996700000001", Cfg)
        first = await sale_check.mark(cid, "won", Cfg, "ademi")
        second = await sale_check.mark(cid, "won", Cfg, "ademi")
        conv = await store.get("frunze_tours:996700000001")
        await engine.dispose()
        return first[0], second[0], conv

    first, second, conv = run(scenario())
    assert first == "saved"
    assert second == "repeat"
    assert conv.outcome == "won"
    assert portal == ["180001"], f"походов в портал: {portal}"


def test_thinking_tap_defers_and_writes_no_outcome(tmp_path, monkeypatch):
    """«Ещё думает» не портит отчёт и не выбрасывает диалог из опроса навсегда."""
    from app.integrations.panel import store as store_mod

    async def scenario():
        engine, store = await _store(tmp_path, [_row()], name="think.db")
        monkeypatch.setattr(store_mod, "get_conversation_store", lambda: store)
        cid = sale_check._cid("frunze_tours:996700000001", Cfg)
        result, _ = await sale_check.mark(cid, "thinking", Cfg, "ademi")
        conv = await store.get("frunze_tours:996700000001")
        await engine.dispose()
        return result, conv

    result, conv = run(scenario())
    assert result == "snoozed"
    assert conv.outcome == "manager"        # авто-статус на месте, исход не выдуман
    assert conv.sale_check_snooze_until is not None


def test_unknown_link_says_so(tmp_path, monkeypatch):
    """Битая или устаревшая ссылка — отдельный ответ, а не «уже отмечено»."""
    from app.integrations.panel import store as store_mod

    async def scenario():
        engine, store = await _store(tmp_path, [_row()], name="unknown.db")
        monkeypatch.setattr(store_mod, "get_conversation_store", lambda: store)
        result, conv = await sale_check.mark("no-such-cid", "won", Cfg, "ademi")
        await engine.dispose()
        return result, conv

    result, conv = run(scenario())
    assert result == "unknown"
    assert conv is None


def test_get_does_not_write_only_post_does(tmp_path, monkeypatch):
    """Открытие ссылки обязано быть безопасным.

    Telegram строит превью, сходив GET-ом по первой ссылке в сообщении; то же делают
    антивирус на телефоне и предзагрузка браузера. Если GET записывает — продажа
    отмечается ботом в первый же вечер, и цифра, ради честности которой всё затевалось,
    становится враньём.
    """
    from fastapi.testclient import TestClient

    from app.integrations.panel import store as store_mod

    async def prepare():
        return await _store(tmp_path, [_row()], name="http.db")

    engine, store = run(prepare())
    portal: list[str] = []

    async def fake_convert(conv_key, lead_id, *, conv=None):
        portal.append(lead_id)

    monkeypatch.setattr(store_mod, "get_conversation_store", lambda: store)
    monkeypatch.setattr(sale_check, "_convert_lead", fake_convert)
    monkeypatch.setattr(settings, "webhook_secret", "test-secret")
    monkeypatch.setattr(settings, "public_base_url", "https://frunzetravel.kg")
    monkeypatch.setattr(settings, "bitrix_portal_url", "https://getvisakg.bitrix24.kz")

    import app.main as main_mod

    token = sale_check.make_link("frunze_tours:996700000001", "won",
                                 settings, "ademi").rsplit("/", 1)[-1]
    with TestClient(main_mod.app) as client:
        page = client.get(f"/sale/{token}")
        assert page.status_code == 200
        assert "Подтвердить" in page.text
        # менеджер сверяет записанное ботом здесь же, не открывая Битрикс
        assert "Бот записал так" in page.text
        assert "направление" in page.text and "Турция" in page.text
        assert "/crm/lead/details/180001/" in page.text
        assert run(store.get("frunze_tours:996700000001")).outcome == "manager"
        assert portal == [], "GET сходил в портал — превью Telegram отметит продажу само"

        done = client.post(f"/sale/{token}")
        assert done.status_code == 200
        assert run(store.get("frunze_tours:996700000001")).outcome == "won"
        assert portal == ["180001"]

    run(engine.dispose())


def test_each_manager_has_a_separate_day_latch(tmp_path, monkeypatch):
    """ЗАМЕР 11.09: защёлка «сегодня уже спросили» была ОДНА на всех менеджеров.

    По турам менеджеров двое, и трафик поделён почти поровну (356 диалогов у одной,
    375 у другой). С общей защёлкой утренняя рассылка одной из них закрывала день
    второй — то есть половина продаж не измерялась бы вообще. У календарного брифа
    защёлка давно пер-менеджерная, здесь её просто забыли развести.
    """
    from app.integrations.panel import store as store_mod

    sent: list[str] = []

    async def fake_push(token, chat_id, text, **kwargs):
        sent.append(chat_id)
        return True

    async def scenario():
        flags.reset()
        engine, store = await _store(
            tmp_path,
            [_row(), _row("frunze_tours:996700000002", assigned_to="aisina")],
            name="latch.db")
        monkeypatch.setattr(store_mod, "get_conversation_store", lambda: store)
        monkeypatch.setattr(settings, "managers", [
            ManagerConfig(login="ademi", password="x", telegram_chat_id="111"),
            ManagerConfig(login="aisina", password="x", telegram_chat_id="222"),
        ])
        monkeypatch.setattr(settings, "sale_check_managers", ["ademi", "aisina"])
        monkeypatch.setattr(settings, "sale_check_enabled", True)
        monkeypatch.setattr(settings, "sale_check_hour", 18)
        monkeypatch.setattr(settings, "webhook_secret", "test-secret")
        monkeypatch.setattr(settings, "public_base_url", "https://frunzetravel.kg")
        monkeypatch.setattr("app.core.calendar_brief._token", lambda: "tg-token")
        monkeypatch.setattr("app.core.calendar_brief._push_telegram", fake_push)

        # Одной уже писали сегодня — вторая всё равно обязана получить своё.
        await flags.set_flag(f"sale_check_sent_ademi_{NOW:%Y%m%d}", True)
        await sale_check.run(NOW)
        await sale_check.run(NOW + timedelta(minutes=5))   # следующий тик того же часа
        await engine.dispose()

    run(scenario())
    assert sent == ["222"], f"ожидали письмо только второй менеджеру, ушло: {sent}"


# ======================================================================================
# РЕШЕНИЕ АЛАНА 11.09: туровые заказы общие, по владельцу их не делим.
#
# Замер: трафик поделён почти поровну (356 диалогов у одной менеджерки, 375 у другой),
# а 29 туровых диалогов в неделю (17%) не закреплены ни за кем — при отборе по владельцу
# про них не спросили бы никогда. Поэтому очередь одна, список один на обеих, кто первый
# нажал — тот и закрыл.
# ======================================================================================

def test_queue_is_shared_and_includes_ownerless(tmp_path, monkeypatch):
    """Обе менеджерки получают ОДИН И ТОТ ЖЕ список, включая ничейные диалоги."""
    from app.integrations.panel import store as store_mod

    sent: list[tuple[str, str]] = []

    async def fake_push(token, chat_id, text, **kwargs):
        sent.append((chat_id, text))
        return True

    async def scenario():
        flags.reset()
        engine, store = await _store(tmp_path, [
            _row("frunze_tours:996700000001", assigned_to="ademi"),
            _row("frunze_tours_sezim:996700000002", assigned_to="aisina"),
            _row("frunze_tours:996700000003", assigned_to=""),      # ничей
        ], name="shared.db")
        monkeypatch.setattr(store_mod, "get_conversation_store", lambda: store)
        monkeypatch.setattr(settings, "managers", [
            ManagerConfig(login="ademi", password="x", telegram_chat_id="111"),
            ManagerConfig(login="aisina", password="x", telegram_chat_id="222"),
        ])
        monkeypatch.setattr(settings, "sale_check_managers", ["ademi", "aisina"])
        monkeypatch.setattr(settings, "sale_check_enabled", True)
        monkeypatch.setattr(settings, "sale_check_hour", 18)
        monkeypatch.setattr(settings, "webhook_secret", "test-secret")
        monkeypatch.setattr(settings, "public_base_url", "https://frunzetravel.kg")
        monkeypatch.setattr("app.core.calendar_brief._token", lambda: "tg-token")
        monkeypatch.setattr("app.core.calendar_brief._push_telegram", fake_push)
        await sale_check.run(NOW)
        conv = await store.get("frunze_tours:996700000003")
        await engine.dispose()
        return conv

    ownerless = run(scenario())
    assert sorted(c for c, _ in sent) == ["111", "222"], f"ушло не обеим: {sent}"
    for _, text in sent:
        assert "0001" in text and "0002" in text and "0003" in text, \
            "список не общий: в нём нет всех троих"
    assert ownerless.sale_check_asked_at is not None, "ничейный диалог не отмечен спрошенным"


def test_message_shows_who_leads_the_dialog():
    """Раз список общий, менеджер должен видеть, свой это клиент или коллеги."""
    convs = [Conv("frunze_tours:996700004477", stage="manager", assigned_to="aisina"),
             Conv("frunze_tours:996700008812", stage="manager", assigned_to="")]
    text = sale_check.render_message(convs, Cfg, NOW, "ademi")
    assert "aisina" in text.lower()
    assert "ничей" in text.lower()


# ======================================================================================
# РЕВЬЮ 11.09 — две дыры в общей очереди.
# ======================================================================================

def test_partial_delivery_does_not_burn_the_day(tmp_path, monkeypatch):
    """Сорвалась доставка одной — диалоги НЕ помечаем, иначе вторая теряет день молча.

    Список считается один раз и помечается «спрошенным» в конце. Если первой доставили,
    а второй нет, пометка выбрасывала вторую из сегодняшнего дня навсегда: на следующем
    тике отбор возвращал пусто, а назавтра диалоги уже вне окна свежести. Ровно тот исход,
    который эта фича должна была починить, только наступающий от одной сетевой ошибки.
    """
    from app.integrations.panel import store as store_mod

    sent: list[str] = []

    async def flaky_push(token, chat_id, text, **kwargs):
        if chat_id == "222":
            return False                   # второй менеджер недоступен
        sent.append(chat_id)
        return True

    async def scenario():
        flags.reset()
        engine, store = await _store(tmp_path, [_row()], name="partial.db")
        monkeypatch.setattr(store_mod, "get_conversation_store", lambda: store)
        monkeypatch.setattr(settings, "managers", [
            ManagerConfig(login="ademi", password="x", telegram_chat_id="111"),
            ManagerConfig(login="aisina", password="x", telegram_chat_id="222"),
        ])
        monkeypatch.setattr(settings, "sale_check_managers", ["ademi", "aisina"])
        monkeypatch.setattr(settings, "sale_check_enabled", True)
        monkeypatch.setattr(settings, "sale_check_hour", 18)
        monkeypatch.setattr(settings, "webhook_secret", "test-secret")
        monkeypatch.setattr(settings, "public_base_url", "https://frunzetravel.kg")
        monkeypatch.setattr("app.core.calendar_brief._token", lambda: "tg-token")
        monkeypatch.setattr("app.core.calendar_brief._push_telegram", flaky_push)
        await sale_check.run(NOW)
        conv = await store.get("frunze_tours:996700000001")
        await engine.dispose()
        return conv

    conv = run(scenario())
    assert sent == ["111"], sent
    assert conv.sale_check_asked_at is None, \
        "диалог помечен спрошенным, хотя вторая менеджерка сообщение не получила"


def test_own_service_numbers_are_not_asked_about():
    """Наши собственные номера — это партнёрские чаты, а не клиенты.

    В очередь на 11.09 попали +996707660009 и +996706660009 — номера самих ботов
    Frunze Travel и GetVisa. Переписка там про ваучеры и страховые полисы с коллегами;
    вопрос «клиент оплатил?» по ним бессмыслен, а нажатие «Оплатил» заведёт сделку
    в боевом портале.
    """
    own = [Conv("frunze_tours:996707660009", stage="manager"),
           Conv("frunze_tours:996706660009", stage="manager")]
    client = Conv("frunze_tours:996700004477", stage="manager")
    assert sale_check.select_targets(own + [client], NOW, Cfg) == [client]


# ======================================================================================
# 🔴 ЗАМЕР 11.09 16:23 — мина, взведённая в боевой очереди.
#
# В портале есть «общие карточки» Открытой линии: один лид хранит десятки разных
# телефонов. Замер: таких карточек 74, на них висят 203 туровых диалога; на лиде 181665
# сидят 19 наших клиентов. В вечерней очереди на сегодня 3 кандидата из 5 — на общих
# карточках.
#
# Нажатие «Оплатил» по такому диалогу уводит в «Подписан» карточку ВСЕХ, кто на ней
# сидит. Дальше обратное чтение выбирает из них ОДИН произвольный диалог, ставит ему
# «продано» и заводит сделку с именем чужого клиента, а остальные выпадают из конвейера
# навсегда — их стадия становится терминальной.
#
# Две линии защиты, потому что ссылки уже разосланы и лежат у менеджера в телефоне:
#   1) такие диалоги не попадают в новые рассылки;
#   2) нажатие по уже отправленной ссылке не трогает портал.
# ======================================================================================

def _shared(key, lead, **kw):
    c = Conv(key, stage="manager", **kw)
    c.bitrix_lead_id = lead
    return c


def test_dialogs_on_a_shared_card_are_not_asked_about():
    """Первая линия: общая карточка в вечернюю рассылку не попадает."""
    a = _shared("frunze_tours:996700000001", "181665")
    b = _shared("frunze_tours:996700000002", "181665")   # тот же лид — общая карточка
    solo = _shared("frunze_tours:996700000003", "184417")
    assert sale_check.select_targets([a, b, solo], NOW, Cfg) == [solo]


def test_single_dialog_per_card_still_asked():
    """Ложноположительный, обязан пройти: обычная карточка спрашивается как раньше."""
    solo = _shared("frunze_tours:996700000004", "186777")
    assert sale_check.select_targets([solo], NOW, Cfg) == [solo]


def test_dialog_without_a_card_is_not_treated_as_shared():
    """Диалоги без карточки не должны схлопываться в одну «общую» по пустому id."""
    a = Conv("frunze_tours:996700000005", stage="manager")
    b = Conv("frunze_tours:996700000006", stage="manager")
    a.bitrix_lead_id = b.bitrix_lead_id = ""
    assert len(sale_check.select_targets([a, b], NOW, Cfg)) == 2


def test_convert_refuses_a_shared_card(tmp_path, monkeypatch):
    """Вторая линия: нажатие по УЖЕ отправленной ссылке портал не трогает.

    Ссылки на общие карточки ушли Адеми сегодня утром — отозвать их нельзя, значит
    защита обязана стоять на самом нажатии, а не только в отборе.
    """
    from app.integrations.panel import store as store_mod

    portal: list[str] = []

    async def spy_convert(lead_id, status):
        portal.append(lead_id)

    async def scenario():
        engine, store = await _store(tmp_path, [
            _row("frunze_tours:996700000001", bitrix_lead_id="181665"),
            _row("frunze_tours:996700000002", bitrix_lead_id="181665"),
        ], name="shared_convert.db")
        monkeypatch.setattr(store_mod, "get_conversation_store", lambda: store)

        class FakeCrm:
            async def get_lead(self, lead_id):
                return {"ID": lead_id, "STATUS_ID": "UC_PNSIIB"}

            async def update_stage_status(self, lead_id, status):
                await spy_convert(lead_id, status)

        monkeypatch.setattr("app.integrations.crm.bitrix24.Bitrix24Crm", lambda: FakeCrm())
        cid = sale_check._cid("frunze_tours:996700000001", Cfg)
        result, _ = await sale_check.mark(cid, "won", Cfg, "ademi")
        conv = await store.get("frunze_tours:996700000001")
        await engine.dispose()
        return result, conv

    result, conv = run(scenario())
    assert portal == [], f"общую карточку двинули в портале: {portal}"
    assert conv.outcome == "won", "ответ менеджера всё равно должен сохраниться"
    assert result in ("saved", "saved_no_crm"), result
