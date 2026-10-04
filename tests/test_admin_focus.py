"""ГЕЙТ: экран «Фокус» — кому ответить сейчас. Тумблер `admin_focus_enabled`.

Написан ДО реализации и исполнителем НЕ редактируется.

Зачем экран. Сегодня на вопрос «с кем работать прямо сейчас» отвечают ТРИ разных места:
доска «Диалоги» (семь колонок канбана), «Покупатели сегодня» (триаж по тирам) и «Горячий
лист». Менеджер сам решает, какому верить, и ходит по кругу. «Фокус» отвечает один раз:
вот следующий клиент, вот что он спросил, вот поле ответа.

Что здесь закреплено:

1. **Порядок очереди — смысл экрана.** Дольше ждёт — выше, но рекламный мусор (`is_noise`)
   не имеет права стоять первым: иначе менеджер начинает день с «Можно узнать подробнее?»
   по ссылке из инстаграма.
2. **Экран собран из существующих действий.** Отправка, перехват и архив — те же
   эндпоинты, что у доски. Новых путей к отправке сообщения клиенту не появляется.
3. **Пустая очередь — осмысленный экран**, а не поломка и не пустота.
4. **Откат мгновенный:** тумблер OFF — маршрута нет, меню прежнее.
5. **Движение выключается** по `prefers-reduced-motion`, и тяжёлые эффекты не включаются
   на узком экране: менеджеры работают с телефонов, и «максимум эффектов» не должен
   превратиться в тормоза.

Проверки смотрят на ОТРЕНДЕРЕННУЮ страницу, а не на файл шаблона. Урок 02.10: гейт,
читавший шаблон с диска, не упал, когда весь новый вид подменили на `{% if False %}`.
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

import app.admin.router as admin_router
import app.config
import app.main as main
from app.config import ManagerConfig
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

FLAG = "admin_focus_enabled"
URL = "/admin/focus"


def _clear():
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    from app.core import flags
    flags.reset()


def _managers(monkeypatch):
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
    ], raising=False)


def _on(monkeypatch, value=True):
    monkeypatch.setattr(app.config.settings, FLAG, value, raising=False)


def _login():
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login",
                       data={"login": "admin", "password": "frunze"}).status_code == 200
    return client


def _seed(user, text, minutes_ago, *, name="", bot_id="getvisa", funnel="visa",
          sender="client", **meta):
    """Диалог, где последним писал клиент — то есть он ждёт ответа."""
    store = get_conversation_store()

    async def _s():
        await store.add_message(user, sender, text, channel="whatsapp",
                                bot_id=bot_id, phone=user.split(":")[-1])
        conv = panel_store._memory_store._conv[user]
        conv.last_message_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        for m in conv.messages:
            m.created_at = conv.last_message_at
        kwargs = {"funnel": funnel}
        if name:
            kwargs["qualification"] = {"name": name}
        kwargs.update(meta)
        await store.update_meta(user, **kwargs)
    asyncio.run(_s())


# --- A. Порядок очереди — смысл экрана ---------------------------------------

def test_longest_waiting_client_goes_first(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000001", "жду ответа третий час", 185, name="Азамат")
    _seed("getvisa:996700000002", "здравствуйте", 12, name="Нурия")
    body = _login().get(URL).text
    assert body.index("Азамат") < body.index("Нурия"), "первым идёт не тот, кто ждёт дольше"


def test_advertising_noise_never_leads_the_queue(monkeypatch):
    """Рекламный мусор ждёт дольше всех, но начинать день с него — потеря времени.

    Правка гейта: рекламный лид засевается БЕЗ имени. `leadstate.is_noise` считает шумом
    только диалог с пустой квалификацией — задав имя, прежняя фикстура сама отменяла
    признак шума и проверяла не то. Ломалось моё утверждение, не требование.
    """
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000003", "https://instagram.com/p/Cxyz Можно узнать подробнее?", 600)
    _seed("getvisa:996700000004", "нужна виза в США, когда можно подать?", 30, name="Руслан")
    body = _login().get(URL).text
    assert body.index("Руслан") < body.index("996700000003"), "рекламный лид встал первым"


def test_queue_shows_who_is_next_after_the_current_one(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    for i, (minutes, name) in enumerate([(180, "Первый"), (90, "Второй"), (30, "Третий")]):
        _seed(f"getvisa:99670000001{i}", "вопрос по визе", minutes, name=name)
    body = _login().get(URL).text
    for name in ("Первый", "Второй", "Третий"):
        assert name in body, f"{name} пропал из экрана"


def test_clients_who_do_not_wait_are_not_in_the_queue(monkeypatch):
    """Последним писал менеджер — клиент не ждёт, в фокусе ему не место."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000020", "записал вас на 14 октября", 20, name="Отвеченный",
          sender="manager")
    _seed("getvisa:996700000021", "а что по срокам?", 25, name="Ждущий")
    body = _login().get(URL).text
    assert "Ждущий" in body
    assert "Отвеченный" not in body, "в фокус попал клиент, которому уже ответили"


# --- B. Экран собран из существующих действий --------------------------------

def test_focus_reuses_existing_endpoints(monkeypatch):
    """Новых путей к отправке сообщения клиенту не появляется — только те, что уже есть."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000030", "сколько стоит виза?", 40, name="Азамат")
    body = _login().get(URL).text
    for action in ("/send", "/takeover", "/archive", "/suggest"):
        assert action in body, f"на экране нет действия {action}"


def test_focus_shows_what_the_client_actually_asked(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000031", "виза в США сколько стоит и сколько ждать?", 40,
          name="Азамат")
    body = _login().get(URL).text
    assert "сколько стоит и сколько ждать" in body, "реплики клиента нет на экране"


def test_ai_brief_is_shown_when_there_is_one(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000032", "а по срокам?", 40, name="Азамат",
          ai_summary="спрашивал про сроки, бюджет не назвал",
          manager_next_step="уточнить бюджет и предложить запись")
    body = _login().get(URL).text
    assert "спрашивал про сроки" in body, "брифа ИИ нет на экране"
    assert "уточнить бюджет" in body, "следующего шага нет на экране"


def test_lead_without_brief_still_renders(monkeypatch):
    """Брифа нет у большинства диалогов — экран не имеет праваから этого ломаться."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000033", "здравствуйте", 40, name="Безбрифа")
    r = _login().get(URL)
    assert r.status_code == 200 and "Безбрифа" in r.text


# --- C. Пустая очередь --------------------------------------------------------

def test_empty_queue_is_a_designed_screen(monkeypatch):
    """Правка гейта: прежнее условие «одно из двух» проходило, когда заголовок уже сломан,
    потому что хватало второй строки. Требуем и заголовок, и объяснение."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    r = _login().get(URL)
    assert r.status_code == 200, "пустая очередь ломает экран"
    assert "Все ответили" in r.text, "у пустого экрана нет внятного заголовка"
    assert "никто не ждёт" in r.text.lower(), "пустой экран не объяснён человеку"


# --- D. Откат мгновенный ------------------------------------------------------

def test_flag_off_hides_the_screen(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch, False)
    assert _login().get(URL).status_code == 404, "при выключенном тумблере экран доступен"


def test_flag_off_keeps_the_menu_unchanged(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch, False)
    assert URL not in _login().get("/admin").text, "в меню осталась ссылка на выключенный экран"


def test_flag_on_puts_focus_in_the_menu(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    assert URL in _login().get("/admin").text, "включённый экран не попал в меню"


def test_flag_defaults_to_off():
    assert app.config.settings.admin_focus_enabled is False


def test_flag_is_switchable_without_deploy():
    assert FLAG in admin_router.FEATURE_FLAGS


# --- E. Движение не должно мешать работать -----------------------------------

def _focus_css(body: str) -> str:
    """CSS именно этого экрана. Общий блок оболочки не считается: правка гейта 02–03.10 —
    проверка по всей странице проходила за счёт `prefers-reduced-motion` в `base.html`."""
    start = body.find(".focus-wrap")
    assert start != -1, "на странице нет стилей экрана «Фокус»"
    return body[start:body.find("</style>", start)]


def test_motion_can_be_turned_off_by_the_system(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    css = _focus_css(_login().get(URL).text)
    assert "prefers-reduced-motion" in css, (
        "движение экрана не отключается системной настройкой")
    block = css[css.find("prefers-reduced-motion"):]
    assert "animation: none" in block, "анимации не гасятся при reduced-motion"


def test_heavy_effects_are_not_applied_on_phones(monkeypatch):
    """Размытие и свечение дороги. Менеджеры работают с телефонов, и «максимум эффектов»
    не должен превращаться в тормоза на слабом устройстве."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    css = _focus_css(_login().get(URL).text)
    assert "backdrop-filter" in css, "стекла нет вовсе — эффекты не сделаны"
    narrow = css[css.find("@media (max-width: 760px)"):]
    assert narrow, "нет блока для телефона"
    assert "backdrop-filter: none" in narrow, "на телефоне размытие не отключено"


def test_waiting_timer_is_live(monkeypatch):
    """Таймер ожидания тикает: экран показывает, что клиент ждёт ПРЯМО сейчас."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000040", "жду", 65, name="Азамат")
    body = _login().get(URL).text
    # Атрибут ищем в РАЗМЕТКЕ карточки, а не где угодно: в скрипте то же имя встречается
    # при чтении, и поиск по всей странице проходил даже без самого атрибута.
    lead = body[body.find('<article class="lead"'):body.find("</article>")]
    assert "data-wait-since=" in lead, "нет точки отсчёта для живого таймера"
    assert "setInterval(tick" in body, "таймер ожидания не обновляется каждую секунду"


# --- F. Скоуп менеджера соблюдается ------------------------------------------

def test_scoped_manager_sees_only_his_direction(monkeypatch):
    """Фокус не имеет права показать визовому менеджеру туровый лид: правило скоупа
    действует здесь так же, как на доске."""
    _clear()
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="medina", name="Медина", password="pw"),
    ], raising=False)
    _on(monkeypatch)
    _seed("frunze_tours:996700000050", "хочу тур в Турцию", 200, name="Туровый",
          bot_id="frunze_tours", funnel="tours")
    _seed("getvisa:996700000051", "нужна виза", 20, name="Визовый")
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login",
                       data={"login": "medina", "password": "pw"}).status_code == 200
    body = client.get(URL).text
    assert "Туровый" not in body, "визовый менеджер видит туровый лид в фокусе"


# --- G. Находки независимого ревью 03.10 -------------------------------------
#
# Ревью нашло три дефекта поведения, которых гейт не видел: он проверял HTML и ничего
# не знал про JS и htmx. Тесты ниже закрывают именно их.

def test_hotkeys_ignore_modifier_combinations(monkeypatch):
    """Ctrl+A вне поля не должен архивировать клиента.

    Прежний обработчик смотрел только на `e.key`: Ctrl+A давал `'a'`, срабатывал клик по
    «В архив» и перезагрузка. Клиент уезжал в архив одной случайной комбинацией.
    """
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    body = _login().get(URL).text
    hot = body[body.find("keydown"):]
    assert "e.ctrlKey" in hot and "e.metaKey" in hot and "e.altKey" in hot, (
        "горячие клавиши не отсеивают сочетания с модификаторами")


def test_archive_from_keyboard_asks_for_confirmation(monkeypatch):
    """Архив необратим для менеджера: с клавиши — только через подтверждение."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000060", "вопрос", 30, name="Азамат")
    body = _login().get(URL).text
    # Подтверждение может быть своим `confirm(...)` или штатным `hx-confirm` — требование
    # в том, что оно есть, а не в том, каким механизмом сделано.
    archive = body[body.find('id="act-archive"'):]
    archive = archive[:archive.find("</button>")]
    assert "hx-confirm" in archive or "confirm(" in archive, (
        "архив идёт без подтверждения")


def test_screen_waits_for_the_server_before_moving_on(monkeypatch):
    """Карточка улетает ТОЛЬКО после успешного ответа сервера.

    Отправка идёт во внешний канал (Wappi) и отвечает не мгновенно. Перезагрузка по
    таймеру отменяла запрос, а отказ (диалог закреплён за другим менеджером, канал вернул
    ошибку) уходил в скрытый блок — менеджер считал, что ответил, клиент ждал дальше.
    """
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000061", "вопрос", 30, name="Азамат")
    body = _login().get(URL).text
    assert "htmx:afterRequest" in body, "экран не ждёт ответа сервера"
    assert "detail.successful" in body, "успех запроса не проверяется"
    assert 'onsubmit="flyAway()"' not in body, "карточка всё ещё улетает по таймеру"


def test_failure_is_shown_to_the_manager(monkeypatch):
    """Отказ обязан быть виден: иначе он не отказ, а молчание."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000062", "вопрос", 30, name="Азамат")
    body = _login().get(URL).text
    assert 'id="after-send" hidden' not in body, (
        "блок ответа сервера скрыт — отказ отправки менеджер не увидит")


def test_empty_answer_is_not_sent(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000063", "вопрос", 30, name="Азамат")
    body = _login().get(URL).text
    assert "trim()" in body[body.find("answer-form"):], "пустой ответ уходит на сервер"


def test_skip_moves_to_the_next_lead(monkeypatch):
    """«Позже» переключает текущего лида на сервере, а не грузит партиал в скрытый блок."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000070", "первый", 180, name="Первый")
    _seed("getvisa:996700000071", "второй", 90, name="Второй")
    client = _login()
    body = client.get(URL).text
    assert "/admin/focus?lead=" in body, "очередь не ведёт к выбору следующего лида"


def test_lead_parameter_picks_that_client(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000072", "первый", 180, name="Первый")
    _seed("getvisa:996700000073", "второй", 90, name="Второй")
    body = _login().get(URL, params={"lead": "getvisa:996700000073"}).text
    head = body[body.find('class="lead-name"'):body.find('class="lead-phone"')]
    assert "Второй" in head, "параметр lead не выбрал запрошенного клиента"


def test_unknown_lead_parameter_falls_back_to_the_queue(monkeypatch):
    """Чужой или устаревший id не ломает экран и не показывает чужой лид."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000074", "первый", 180, name="Первый")
    r = _login().get(URL, params={"lead": "frunze_tours:996700999999"})
    assert r.status_code == 200 and "Первый" in r.text


def test_wait_since_is_timezone_aware(monkeypatch):
    """Naive-время браузер разберёт как местное — в Бишкеке это сдвиг на 6 часов."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000075", "вопрос", 65, name="Азамат")
    body = _login().get(URL).text
    import re
    m = re.search(r'data-wait-since="([^"]+)"', body)
    assert m, "нет точки отсчёта таймера"
    stamp = m.group(1)
    assert stamp.endswith("+00:00") or stamp.endswith("Z") or "+" in stamp[10:], (
        f"время без часового пояса: {stamp}")


def test_send_hint_names_the_real_shortcut(monkeypatch):
    """В textarea Enter переводит строку. Обещать им отправку — врать менеджеру."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000076", "вопрос", 30, name="Азамат")
    body = _login().get(URL).text
    send_btn = body[body.find('class="act act-send"'):]
    send_btn = send_btn[:send_btn.find("</button>")]
    assert "Ctrl" in send_btn or "⌘" in send_btn, "кнопка обещает отправку по Enter"


# --- H. Гибкость под экран (требование Алана 03.10) --------------------------
#
# «Фокус» был зажат в колонку 760px по центру: на широком мониторе половина экрана
# пустовала, хотя там просится контекст переписки. На телефоне наоборот — всё в одну
# колонку, без лишнего.

def test_wide_screen_gets_two_columns(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000080", "вопрос", 30, name="Азамат")
    css = _focus_css(_login().get(URL).text)
    wide = css[css.find("@media (min-width: 1100px)"):]
    assert wide, "нет раскладки для широкого экрана"
    assert "grid-template-columns" in wide, "на широком экране по-прежнему одна колонка"


def test_narrow_screen_stays_one_column(monkeypatch):
    """Телефон — одна колонка: две там превращаются в кашу."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    css = _focus_css(_login().get(URL).text)
    base = css[:css.find("@media (min-width: 1100px)")]
    layout = base[base.find(".focus-wrap"):base.find("}", base.find(".focus-wrap"))]
    assert "grid-template-columns" not in layout, (
        "двухколоночная раскладка применяется по умолчанию, а не только на широком экране")


def test_history_is_shown_next_to_the_lead(monkeypatch):
    """Отвечая, менеджер должен видеть, о чём уже говорили."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    user = "getvisa:996700000081"
    _seed(user, "а по срокам?", 30, name="Азамат")
    store = get_conversation_store()

    async def _more():
        await store.add_message(user, "bot", "Виза США — 250$, срок около месяца",
                                channel="whatsapp", bot_id="getvisa")
        await store.add_message(user, "client", "а если срочно?", channel="whatsapp",
                                bot_id="getvisa")
    asyncio.run(_more())

    body = _login().get(URL).text
    assert "срок около месяца" in body, "истории переписки нет рядом с лидом"
    assert "а если срочно" in body


def test_history_does_not_drag_the_whole_dialog(monkeypatch):
    """Диалог может быть на сотни реплик — тащить его целиком незачем."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    user = "getvisa:996700000082"
    _seed(user, "первое сообщение", 30, name="Азамат")
    store = get_conversation_store()

    async def _many():
        for i in range(40):
            await store.add_message(user, "client", f"реплика номер {i}",
                                    channel="whatsapp", bot_id="getvisa")
    asyncio.run(_many())

    body = _login().get(URL).text
    shown = sum(1 for i in range(40) if f"реплика номер {i}" in body)
    assert shown <= 12, f"в историю попало {shown} реплик — это весь диалог целиком"
    assert "реплика номер 39" in body, "последней реплики нет — показана не та часть"


def test_full_dialog_is_one_click_away(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000083", "вопрос", 30, name="Азамат")
    body = _login().get(URL).text
    assert "?open=getvisa%3A996700000083" in body or "?open=getvisa:996700000083" in body, (
        "из фокуса нельзя открыть диалог целиком")


# --- I. HTTP 200 не доказывает отправку, «Позже» не теряет хвост очереди --------


def test_send_denied_reports_outcome_without_sending(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    user = "getvisa:996700000090"
    _seed(user, "вопрос", 30, name="Азамат", assigned_to="medina")
    notice = "Диалог ведёт medina. Сначала передайте лид — затем пишите."
    guard = AsyncMock(return_value=(False, notice))
    send = AsyncMock()
    monkeypatch.setattr(admin_router, "_ownership_guard", guard)
    monkeypatch.setattr(admin_router.outbound, "send_to_client", send)

    r = _login().post(f"/admin/conversation/{user}/send", data={"text": "Ответ"})

    assert r.status_code == 200
    assert r.headers["X-Action-Outcome"] == "denied"
    assert notice in r.text, "обычная карточка должна сохранить причину отказа"
    assert guard.await_args.args[2] == "send"
    send.assert_not_awaited()
    conv = asyncio.run(get_conversation_store().get(user))
    assert conv.assigned_to == "medina" and not conv.intercepted
    assert len(conv.messages) == 1


def test_send_channel_failure_reports_outcome_and_stores_failed_message(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    user = "getvisa:996700000091"
    _seed(user, "вопрос", 30, name="Азамат")
    monkeypatch.setattr(admin_router, "_ownership_guard", AsyncMock(return_value=(True, "")))
    send = AsyncMock(side_effect=RuntimeError("channel unavailable"))
    monkeypatch.setattr(admin_router.outbound, "send_to_client", send)

    r = _login().post(f"/admin/conversation/{user}/send", data={"text": "Ответ"})

    assert r.status_code == 200
    assert r.headers["X-Action-Outcome"] == "failed"
    send.assert_awaited_once()
    conv = asyncio.run(get_conversation_store().get(user))
    assert len(conv.messages) == 2
    message = conv.messages[-1]
    assert message.sender == "manager" and message.text == "Ответ"
    assert message.status == "failed"


def test_send_success_reports_sent_and_keeps_auto_intercept(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    user = "getvisa:996700000092"
    _seed(user, "вопрос", 30, name="Азамат")
    monkeypatch.setattr(admin_router, "_ownership_guard", AsyncMock(return_value=(True, "")))
    send = AsyncMock(return_value="focus-test-provider-id")
    monkeypatch.setattr(admin_router.outbound, "send_to_client", send)

    r = _login().post(f"/admin/conversation/{user}/send", data={"text": "Ответ"})

    assert r.status_code == 200
    assert r.headers["X-Action-Outcome"] == "sent"
    send.assert_awaited_once_with("whatsapp", "getvisa", user, "Ответ")
    conv = asyncio.run(get_conversation_store().get(user))
    assert conv.intercepted and conv.assigned_to == "admin"
    assert conv.messages[-1].status == "sent"
    assert conv.messages[-1].provider_msg_id == "focus-test-provider-id"


def test_send_empty_reports_outcome_without_side_effects(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    user = "getvisa:996700000093"
    _seed(user, "вопрос", 30, name="Азамат")
    guard, send = AsyncMock(), AsyncMock()
    monkeypatch.setattr(admin_router, "_ownership_guard", guard)
    monkeypatch.setattr(admin_router.outbound, "send_to_client", send)

    r = _login().post(f"/admin/conversation/{user}/send", data={"text": " \n\t "})

    assert r.status_code == 200
    assert r.headers["X-Action-Outcome"] == "empty"
    guard.assert_not_awaited()
    send.assert_not_awaited()
    conv = asyncio.run(get_conversation_store().get(user))
    assert len(conv.messages) == 1
    assert not conv.intercepted and not conv.assigned_to


def test_takeover_denied_reports_outcome_without_changing_owner(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    user = "getvisa:996700000094"
    _seed(user, "вопрос", 30, name="Азамат", assigned_to="medina")
    notice = "Диалог ведёт medina. Перехват запрещён."
    guard = AsyncMock(return_value=(False, notice))
    monkeypatch.setattr(admin_router, "_ownership_guard", guard)

    r = _login().post(f"/admin/conversation/{user}/takeover")

    assert r.status_code == 200
    assert r.headers["X-Action-Outcome"] == "denied"
    assert notice in r.text
    assert guard.await_args.args[2] == "claim"
    conv = asyncio.run(get_conversation_store().get(user))
    assert conv.assigned_to == "medina" and not conv.intercepted


def test_takeover_success_reports_claimed(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    user = "getvisa:996700000095"
    _seed(user, "вопрос", 30, name="Азамат")
    monkeypatch.setattr(admin_router, "_ownership_guard", AsyncMock(return_value=(True, "")))

    r = _login().post(f"/admin/conversation/{user}/takeover")

    assert r.status_code == 200
    assert r.headers["X-Action-Outcome"] == "claimed"
    conv = asyncio.run(get_conversation_store().get(user))
    assert conv.assigned_to == "admin" and conv.intercepted


def test_focus_actions_do_not_insert_response_bodies(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000096", "вопрос", 30, name="Азамат")
    body = _login().get(URL).text
    for action in ("send", "takeover", "archive"):
        tag = re.search(r'<(?:form|button)\b[^>]*hx-post="[^"]*/' + action + r'"[^>]*>', body)
        assert tag, f"нет действия {action}"
        assert 'hx-swap="none"' in tag.group(), f"{action} вставляет ответ в страницу"
        assert 'hx-target="#after-send"' not in tag.group()


def test_queue_after_second_lead_starts_with_third(monkeypatch):
    """По ссылкам «Позже» должен доходить до хвоста, а не прыгать между первым и вторым."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    users = [f"getvisa:99670000010{i}" for i in range(3)]
    for user, minutes, name in zip(users, (180, 90, 30), ("Первый", "Второй", "Третий")):
        _seed(user, "вопрос по визе", minutes, name=name)

    body = _login().get(URL, params={"lead": users[1]}).text

    links = re.findall(r'<a\b[^>]*class="qrow\b[^"]*"[^>]*href="([^"]+)"', body)
    assert links == [f"{URL}?lead=getvisa%3A996700000102",
                     f"{URL}?lead=getvisa%3A996700000100"]


def test_queue_wraps_to_first_after_last_lead(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    users = [f"getvisa:99670000011{i}" for i in range(3)]
    for user, minutes, name in zip(users, (180, 90, 30), ("Первый", "Второй", "Третий")):
        _seed(user, "вопрос по визе", minutes, name=name)

    body = _login().get(URL, params={"lead": users[2]}).text

    links = re.findall(r'<a\b[^>]*class="qrow\b[^"]*"[^>]*href="([^"]+)"', body)
    assert links == [f"{URL}?lead=getvisa%3A996700000110",
                     f"{URL}?lead=getvisa%3A996700000111"]


# --- F. Добавлено 04.10.2026 по результатам независимого ревью ------------------
# Ревью закрыло три дефекта Фокуса, но назвало два пробела в самих проверках:
# скоуп проверялся на отсутствующем лиде (что ничего не доказывает), а подсказка
# после сбоя предлагала «попробуйте ещё раз» — то есть отправить ВТОРОЕ сообщение.

def _scoped_login(monkeypatch):
    """Менеджер с реальным ограничением: `medina` видит только `getvisa` и `getvisa_tg`
    (`BOT_SCOPE_BY_MANAGER` в `app/core/manager_scope.py`). Логин `admin` для этой
    проверки непригоден: у него скоуп `None`, то есть ограничивать нечего."""
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="medina", name="Медина", password="frunze"),
    ], raising=False)
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login",
                       data={"login": "medina", "password": "frunze"}).status_code == 200
    return client


def test_lead_outside_manager_scope_is_never_shown(monkeypatch):
    """Чужой лид не показывается, даже когда он СУЩЕСТВУЕТ и назван в `?lead=`.

    Прежняя проверка подставляла id, которого нет в базе: такой тест остался бы
    зелёным, даже если скоуп вообще не проверяется. Здесь туровый лид реально лежит
    в хранилище, а менеджер визовый — и видеть его не должен ни текущим, ни в очереди.
    """
    _clear(); _on(monkeypatch)
    _seed("getvisa:996700000120", "нужна виза в США", 90, name="Азамат")
    _seed("frunze_tours:996700000121", "хочу тур в Дубай", 300, name="Чужой",
          bot_id="frunze_tours", funnel="tours")

    body = _scoped_login(monkeypatch).get(URL, params={"lead": "frunze_tours:996700000121"}).text

    assert "Чужой" not in body, "туровый лид показан визовому менеджеру"
    assert "996700000121" not in body, "номер чужого лида попал на страницу"
    assert "Азамат" in body, "свой лид пропал — экран упал в пустоту вместо подмены"


def test_failed_send_sends_manager_to_card_instead_of_retrying(monkeypatch):
    """После сбоя Фокус ведёт в карточку, а не предлагает отправить заново.

    `/send` при сбое уже записал сообщение со статусом `failed`. Повторная отправка
    отсюда создаёт ВТОРОЕ сообщение, а канал мог принять первое и не ответить в срок —
    клиент получит дубль. Досылка того же сообщения живёт в карточке
    (`/conversation/{id}/resend/{message_id}`), поэтому подсказка обязана вести туда.
    Проверяем отрендеренную страницу: именно текст видит менеджер.
    """
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    _seed("getvisa:996700000122", "вопрос по визе", 40, name="Нурия")

    body = _login().get(URL).text

    assert "Повторить" in body, "подсказка после сбоя не ведёт в карточку"
    assert "дубль" in body, "менеджера не предупредили, чем грозит повторная отправка"
    assert "канал не ответил. Попробуйте ещё раз" not in body, \
        "вернулась подсказка, провоцирующая второе сообщение клиенту"
