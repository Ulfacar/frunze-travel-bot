"""ГЕЙТ: ответы заказчика 2.1 и 2.2 от 05.11.2026 — права внутри направления.

Два решения владельца, каждое за своим тумблером (оба OFF по умолчанию):

* 2.1 `manager_sees_direction_cases_enabled` — менеджер видит всех клиентов своего
  направления. До этого правило было обратным и записано в коде словами: «направление
  это команда, а не общий доступ».
* 2.2 `manager_can_take_colleague_dialog_enabled` — менеджер может забрать клиента
  коллеги себе, включая живую переписку. Отменяет правило «перехват чужого запрещён»
  (CLAUDE.md §7) ВНУТРИ направления; между направлениями запрет остаётся.

Главное, что держит этот файл: **выключенные флаги не меняют ничего**, и два правила
(диалоги и услуги) не расходятся. Они описывают одно и то же бизнес-правило в двух
местах, и прошлый опыт проекта — что расходятся они молча.
"""
from __future__ import annotations

import pytest

from app.domain.permissions import Actor, can_reassign
from app.domain.service_authz import (
    can_advance_case, can_reassign_case, can_view_case,
)


class _Assignment:
    """Активное владение диалогом: ровно те поля, которые читает правило."""

    def __init__(self, manager_id: str, active: bool = True) -> None:
        self.manager_id = manager_id
        self.active = active
        self.direction = "visa"


def _medina(**kwargs) -> Actor:
    return Actor(manager_id="medina", allowed_directions=frozenset({"visa"}), **kwargs)


ADMIN = Actor(manager_id="admin", is_full_admin=True)


# --- Дефолт: выключенные флаги ничего не меняют ------------------------------

def test_defaults_are_off_in_settings():
    """Оба флага заведены с дефолтом OFF: выкатили код — поведение прежнее."""
    from app.config import settings
    assert settings.manager_sees_direction_cases_enabled is False
    assert settings.manager_can_take_colleague_dialog_enabled is False


def test_without_the_flag_a_colleagues_case_is_invisible():
    """Прежнее правило целиком: своя услуга видна, чужая в том же направлении — нет."""
    actor = _medina()
    assert can_view_case(actor, direction="visa", owner_login="medina") is True
    assert can_view_case(actor, direction="visa", owner_login="eliza") is False
    assert can_view_case(actor, direction="tours", owner_login="medina") is False


def test_without_the_flag_a_colleagues_client_cannot_be_taken():
    """Прежнее правило: отобрать активного владельца может только администратор."""
    actor = _medina()
    assert can_reassign_case(actor, direction="visa", owner_login="eliza",
                             target_login="medina") is False
    assert can_reassign(actor, _Assignment("eliza"), "medina", "visa") is False
    # Администратору это доступно и было доступно раньше.
    assert can_reassign(ADMIN, _Assignment("eliza"), "medina", "visa") is True


# --- 2.1: видеть всё своё направление ---------------------------------------

def test_with_team_view_a_colleagues_case_becomes_visible():
    actor = _medina(team_view=True)
    assert can_view_case(actor, direction="visa", owner_login="eliza") is True
    assert can_view_case(actor, direction="visa", owner_login=None) is True


def test_team_view_does_not_cross_directions():
    """«Своего направления» — не «всех». Чужое направление закрыто и с флагом."""
    actor = _medina(team_view=True)
    assert can_view_case(actor, direction="tours", owner_login="ademi") is False
    assert can_view_case(actor, direction=None, owner_login="ademi") is False


def test_seeing_is_not_moving():
    """Видеть чужую услугу можно, двигать этап — нет.

    Иначе двое меняли бы этап одной услуги, и в истории нельзя было бы понять, кто
    отвечает за утверждение «документы переданы». Чтобы вмешаться, услугу сначала
    забирают себе — и это остаётся в истории.
    """
    actor = _medina(team_view=True)
    assert can_view_case(actor, direction="visa", owner_login="eliza") is True
    assert can_advance_case(actor, direction="visa", owner_login="eliza") is False
    assert can_advance_case(actor, direction="visa", owner_login="medina") is True


# --- 2.2: забрать клиента коллеги -------------------------------------------

def test_with_the_flag_a_colleagues_client_can_be_taken_to_myself():
    actor = _medina(can_take_colleague=True)
    assert can_reassign_case(actor, direction="visa", owner_login="eliza",
                             target_login="medina") is True
    assert can_reassign(actor, _Assignment("eliza"), "medina", "visa") is True


def test_taking_to_a_third_manager_stays_an_admin_power():
    """Забрать СЕБЕ — можно; распорядиться чужой работой — нет.

    Ответ 2.2 — про «забрать клиента коллеги», то есть взять на себя. Передача
    третьему менеджеру это другое полномочие, и оно осталось у администратора.
    """
    actor = _medina(can_take_colleague=True)
    assert can_reassign_case(actor, direction="visa", owner_login="eliza",
                             target_login="aisina") is False
    assert can_reassign(actor, _Assignment("eliza"), "aisina", "visa") is False


def test_taking_does_not_cross_directions():
    actor = _medina(can_take_colleague=True)
    assert can_reassign_case(actor, direction="tours", owner_login="ademi",
                             target_login="medina") is False
    assert can_reassign(actor, _Assignment("ademi"), "medina", "tours") is False


def test_the_two_flags_are_independent():
    """Раздельные намеренно: на проде гасится одно, а не всё разом."""
    sees = _medina(team_view=True)
    assert can_reassign_case(sees, direction="visa", owner_login="eliza",
                             target_login="medina") is False
    takes = _medina(can_take_colleague=True)
    assert can_view_case(takes, direction="visa", owner_login="eliza") is False


@pytest.mark.parametrize("owner,target,allowed", [
    ("eliza", "medina", True),      # забрать себе
    ("eliza", "aisina", False),     # отдать третьему
    ("medina", "medina", True),     # подтвердить себя
    ("", "medina", True),           # ничей
])
def test_dialog_and_case_rules_do_not_diverge(owner, target, allowed):
    """Одно бизнес-правило в двух местах обязано отвечать одинаково.

    `permissions.can_reassign` решает про переписку, `service_authz.can_reassign_case`
    — про услугу. Разойдись они, и менеджер забрал бы переписку, но не дело клиента.
    """
    actor = _medina(can_take_colleague=True)
    assignment = _Assignment(owner) if owner else None
    assert can_reassign(actor, assignment, target, "visa") is allowed
    assert can_reassign_case(actor, direction="visa", owner_login=owner,
                             target_login=target) is allowed


# --- Как право попадает в актор ---------------------------------------------

def test_actor_for_does_not_grant_the_rights_by_itself():
    """Права приходят параметрами, а не из cookie: дефолт — прежнее поведение."""
    from app.core.live_authz import actor_for
    actor = actor_for({"login": "medina"})
    assert actor.team_view is False and actor.can_take_colleague is False
    granted = actor_for({"login": "medina"}, team_view=True, can_take_colleague=True)
    assert granted.team_view is True and granted.can_take_colleague is True


def test_actor_for_request_reads_the_runtime_flags(monkeypatch):
    """Актор запроса читает именно рантайм-флаги, а не только env."""
    import asyncio

    from app.core import flags, live_authz

    seen: list[str] = []

    async def fake_get_flag(key, default):
        seen.append(key)
        return key in {live_authz.TEAM_VIEW_FLAG, live_authz.TAKE_COLLEAGUE_FLAG}

    monkeypatch.setattr(flags, "get_flag", fake_get_flag)
    actor = asyncio.run(live_authz.actor_for_request({"login": "medina"}))
    assert live_authz.TEAM_VIEW_FLAG in seen
    assert live_authz.TAKE_COLLEAGUE_FLAG in seen
    assert actor.team_view is True and actor.can_take_colleague is True


def test_a_full_admin_is_unaffected():
    """У администратора эти права и так были — актор не обязан их нести."""
    assert can_view_case(ADMIN, direction="tours", owner_login="ademi") is True
    assert can_reassign_case(ADMIN, direction="tours", owner_login="ademi",
                             target_login="medina") is True


# --- Руководители направлений (ответы 1.5 и 2.4) -----------------------------

def test_three_leads_over_two_directions_are_accepted(monkeypatch):
    """Структура выдерживает трёх человек на двух направлениях.

    Ответ 2.4: сводку пилота видят Гриша, Даулет и Марсель. Ответ 1.5: Гриша и
    Даулет — по обоим направлениям. Марсель — только визы (решение Алана 05.11:
    он визовый менеджер, туровые цифры ему не нужны).

    ВАЖНОЕ ОГРАНИЧЕНИЕ, которое этот тест фиксирует специально: доступ к сводке
    требует ОДНОВРЕМЕННО и скоупа ботов (`BOT_SCOPE_BY_MANAGER`), и записи в
    `PANEL_DIRECTION_LEADS`. Поэтому запись Гриши в «tours» сама по себе туровую
    сводку не открывает — его менеджерский вход видит только визы (решение 21.10,
    трогать запрещено), а туры он смотрит под `grisha-admin`.
    """
    import app.config
    from app.admin.pilot_summary import allowed_directions

    monkeypatch.setattr(app.config.settings, "panel_direction_leads", {
        "visa": ["grisha", "daulet", "marsel"],
        "tours": ["grisha", "daulet"],
    }, raising=False)

    assert allowed_directions({"login": "grisha"}) == ["visa"]
    assert allowed_directions({"login": "marsel"}) == ["visa"]
    assert allowed_directions({"login": "daulet"}) == ["tours"]
    # Полный админ видит всё и без списка руководителей.
    assert set(allowed_directions({"login": "grisha-admin", "admin": True})) >= {"visa", "tours"}
    # Менеджер, которого в списке нет, сводку не видит вовсе.
    assert allowed_directions({"login": "medina"}) == []


def test_the_new_leads_have_a_bot_scope(monkeypatch):
    """Логин без скоупа ботов не видит ничего — поэтому логины и карта идут парой."""
    from app.core.manager_scope import BOT_SCOPE_BY_MANAGER as scope

    assert scope["daulet"] == {"frunze_tours", "frunze_tours_sezim", "frunze_tours_tg"}
    assert scope["marsel"] == {"getvisa", "getvisa_tg"}
    # Решение 21.10 не тронуто: менеджерский вход Гриши — только визы.
    assert scope["grisha"] == {"getvisa", "getvisa_tg"}


# --- Исправления ревью 09.11.2026 -------------------------------------------

def test_team_view_does_not_grant_the_right_to_change_a_case():
    """«Видеть» и «менять» — разные права, и расширили только первое (ответ 2.1).

    До 09.11 запись по делу авторизовалась `can_view_case`, поэтому флаг открывал
    коллеге запись договора с суммой в чужое дело. См. `can_change_case`.
    """
    from app.domain.service_authz import can_change_case
    sees = _medina(team_view=True)
    assert can_view_case(sees, direction="visa", owner_login="eliza") is True
    assert can_change_case(sees, direction="visa", owner_login="eliza") is False
    # Своё дело менять можно, как и раньше.
    assert can_change_case(sees, direction="visa", owner_login="medina") is True
    # Чужое направление закрыто даже владельцу-однофамильцу.
    assert can_change_case(sees, direction="tours", owner_login="medina") is False
    # Администратор право сохраняет: он оформляет договор за отсутствующего менеджера.
    assert can_change_case(ADMIN, direction="visa", owner_login="eliza") is True


@pytest.mark.parametrize("action,allow_takeover,can_take,admin,expected", [
    ("claim", True, True, False, True),    # осознанное «Взять себе» — для этого флаг и есть
    ("send", True, True, False, False),    # отправка НЕ перехватывает: гонка отбирала лид
    ("release", True, True, False, False), # «вернуть боту» перехватом быть не может
    ("claim", False, True, False, False),  # лента и ручной лид: взятие = подобрать ничьё
    ("claim", True, False, False, False),  # флаг 2.2 выключен — прежнее правило
    ("send", True, False, True, True),     # администратор как раньше
])
def test_only_a_deliberate_claim_may_override_an_active_owner(action, allow_takeover,
                                                              can_take, admin, expected):
    """Перебить активного владельца вправе только осознанный перехват.

    Ревью 09.11.2026: `allow_emergency` отдавался на любое действие, и авто-захват
    ничьего лида на ОТПРАВКЕ в гонке молча менял владельца.
    """
    from app.admin.router import takeover_allowed
    actor = ADMIN if admin else _medina(can_take_colleague=can_take)
    assert takeover_allowed(actor, action, allow_takeover=allow_takeover) is expected
