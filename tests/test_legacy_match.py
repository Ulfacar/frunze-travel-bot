"""E1-04 — приёмка сопоставления старых обращений: AC-07 и AC-36."""
from __future__ import annotations

import dataclasses
import random
from decimal import Decimal

import pytest

from app.domain.legacy_match import (
    AMOUNT_NEEDS_RECONCILIATION, AMOUNT_UNPARSEABLE, MIXED_BITRIX_CARD,
    PHONE_KEY_MISMATCH, UNKNOWN_DIRECTION, UNNORMALIZABLE_PHONE, LegacyDialog,
    Link, plan_links,
)


def dialog(user_id, **kw):
    phone = kw.pop("phone", user_id.split(":", 1)[-1])
    return LegacyDialog(user_id=user_id, phone=phone, **kw)


def test_one_phone_two_directions_is_one_person_with_two_links():
    """Один номер писал на туры и на визы — это один человек и две услуги."""
    plan = plan_links([
        dialog("tours_bot:996700111222", funnel="tours"),
        dialog("visa_bot:996700111222", funnel="visa"),
    ])
    assert [(link.phone, link.direction) for link in plan.links] == [
        ("996700111222", "tours"), ("996700111222", "visa")]
    assert not plan.problems


def test_same_phone_through_different_bots_does_not_duplicate_the_link():
    """Два бота одного направления — один человек, одна связь, оба ключа сохранены."""
    plan = plan_links([
        dialog("frunze:996700111222", funnel="tours"),
        dialog("sezim:996700111222", funnel="tours"),
    ])
    assert len(plan.links) == 1
    assert plan.links[0].legacy_user_ids == ("frunze:996700111222", "sezim:996700111222")


def test_ac36_running_twice_produces_the_identical_plan():
    """AC-36: репетиция идемпотентна — второй прогон даёт тот же план."""
    dialogs = [
        dialog("tours_bot:996700111222", funnel="tours", bitrix_lead_id="101"),
        dialog("visa_bot:996555333444", funnel="visa", sale_amount=250.0,
               sale_currency="usd"),
        dialog("tours_bot:nonsense", phone="не телефон", funnel="tours"),
    ]
    first, second = plan_links(dialogs), plan_links(dialogs)
    assert first == second
    assert first.links == second.links and first.problems == second.problems


def test_ac36_mixed_bitrix_card_is_reported_and_never_merges_two_people():
    """AC-36: один лид Bitrix на два номера — спорная строка, но НЕ слияние людей."""
    plan = plan_links([
        dialog("tours_bot:996700111222", funnel="tours", bitrix_lead_id="777"),
        dialog("tours_bot:996555333444", funnel="tours", bitrix_lead_id="777"),
    ])
    # Два разных человека остались двумя связями — склейки не произошло.
    assert sorted(link.phone for link in plan.links) == ["996555333444", "996700111222"]
    mixed = [p for p in plan.problems if p.kind == MIXED_BITRIX_CARD]
    assert len(mixed) == 1
    assert "объединение запрещено" in mixed[0].detail
    assert set(mixed[0].user_ids) == {"tours_bot:996700111222", "tours_bot:996555333444"}


def test_ac36_identical_names_do_not_merge_different_phones():
    """Совпадение имени не признак одного человека: «Азамат» у нас каждый второй."""
    plan = plan_links([
        dialog("tours_bot:996700111222", funnel="tours"),
        dialog("tours_bot:996555333444", funnel="tours"),
    ])
    assert len(plan.links) == 2


def test_ac36_unmatched_contact_goes_to_the_registry_not_into_a_link():
    """AC-36: несопоставленный контакт попадает в реестр, а не в сопоставление."""
    plan = plan_links([dialog("tours_bot:+996", phone="", funnel="tours")])
    assert plan.links == ()
    assert [p.kind for p in plan.problems] == [UNNORMALIZABLE_PHONE]


def test_unknown_direction_is_not_guessed():
    """Пустая воронка не угадывается: иначе услуга заведётся не того продукта."""
    for funnel in (None, "", "   ", "unknown"):
        plan = plan_links([dialog("bot:996700111222", funnel=funnel)])
        assert plan.links == ()
        assert [p.kind for p in plan.problems] == [UNKNOWN_DIRECTION]


def test_ac07_legacy_amount_never_becomes_a_contract_price():
    """AC-07: старая сумма уходит в реестр на сверку и не попадает в связь."""
    plan = plan_links([
        dialog("tours_bot:996700111222", funnel="tours", sale_amount=1234.5,
               sale_currency="kgs"),
    ])
    assert len(plan.links) == 1
    link = plan.links[0]
    # В связи нет ни суммы, ни валюты — переносить деньги молча нельзя.
    assert not hasattr(link, "amount") and not hasattr(link, "agreed_amount")
    amounts = [p for p in plan.problems if p.kind == AMOUNT_NEEDS_RECONCILIATION]
    assert len(amounts) == 1
    assert "требует сверки" in amounts[0].detail and "1234.5" in amounts[0].detail


@pytest.mark.parametrize("amount", [0, 0.0, -5.0, None, "", float("nan"), float("inf")])
def test_ac07_meaningless_legacy_amounts_do_not_create_review_rows(amount):
    """Нули, минусы и мусор не создают строк сверки — это шум, а не продажа."""
    plan = plan_links([dialog("tours_bot:996700111222", funnel="tours",
                              sale_amount=amount)])
    assert [p for p in plan.problems if p.kind == AMOUNT_NEEDS_RECONCILIATION] == []


def test_ac07_amount_is_reported_exactly_without_float_drift():
    """Сумма показывается как десятичная, а не как хвост float."""
    plan = plan_links([dialog("tours_bot:996700111222", funnel="tours",
                              sale_amount=0.29, sale_currency="usd")])
    detail = [p for p in plan.problems if p.kind == AMOUNT_NEEDS_RECONCILIATION][0].detail
    assert detail.startswith("0.29 USD")
    assert Decimal(detail.split()[0]) == Decimal("0.29")


def test_summary_counts_links_and_every_problem_kind():
    plan = plan_links([
        dialog("tours_bot:996700111222", funnel="tours", sale_amount=100.0,
               sale_currency="usd"),
        dialog("tours_bot:bad", phone="нет", funnel="tours"),
        dialog("tours_bot:996555333444", funnel=None),
    ])
    assert plan.summary == {"links": 1, AMOUNT_NEEDS_RECONCILIATION: 1,
                            UNNORMALIZABLE_PHONE: 1, UNKNOWN_DIRECTION: 1}


def test_outcomes_and_lead_ids_are_collected_for_the_review_report():
    """Исход и лид сохраняются справочно: по ним человек сверяет спорные строки."""
    plan = plan_links([
        dialog("tours_bot:996700111222", funnel="tours", outcome="won",
               bitrix_lead_id="55"),
        dialog("sezim:996700111222", funnel="tours", outcome="lost",
               bitrix_lead_id="56"),
    ])
    link = plan.links[0]
    # Порядок сортированный, а не «как пришло»: план обязан не зависеть от
    # порядка чтения из базы (SELECT идёт без ORDER BY).
    assert link.outcomes == ("lost", "won")
    assert link.bitrix_lead_ids == ("55", "56")

def test_ac36_plan_does_not_depend_on_input_order():
    """AC-36: перестановка входа не меняет план. Первая версия падала 50 раз из 50."""
    dialogs = [
        dialog("tours_bot:996700111222", funnel="tours", bitrix_lead_id="101",
               outcome="won"),
        dialog("sezim:996700111222", funnel="tours", bitrix_lead_id="102",
               outcome="lost"),
        dialog("visa_bot:996555333444", funnel="visa", sale_amount=250.0,
               sale_currency="usd"),
        dialog("tours_bot:996555333444", funnel="tours", bitrix_lead_id="101"),
        dialog("tours_bot:nonsense", phone="не телефон", funnel="tours"),
        dialog("visa_bot:996700999888", funnel=None),
    ]
    reference = plan_links(dialogs)
    for seed in range(50):
        shuffled = list(dialogs)
        random.Random(seed).shuffle(shuffled)
        assert plan_links(shuffled) == reference, f"план разошёлся при seed={seed}"


def test_phone_in_key_conflicting_with_phone_column_is_not_linked():
    """Расхождение ключа и колонки — отказ: иначе диалог утекает к другому человеку."""
    plan = plan_links([
        LegacyDialog(user_id="w:996700111222", phone="996555333444", funnel="tours"),
        dialog("x:996555333444", funnel="tours"),
    ])
    # Чужой диалог не влился в связь второго номера.
    assert [link.legacy_user_ids for link in plan.links] == [("x:996555333444",)]
    assert [p.kind for p in plan.problems] == [PHONE_KEY_MISMATCH]


def test_ac07_amount_is_reported_even_when_the_row_cannot_be_matched():
    """AC-07: продажа с деньгами не теряет пометку «сверить» из-за плохой строки."""
    # Первый случай: номер в порядке, направление неизвестно.
    # Второй: номер не разобрать ни в колонке, ни в ключе диалога.
    for user_id, broken in (("tours_bot:996700111222", {"funnel": None}),
                            ("tours_bot:нет", {"phone": "не телефон",
                                               "funnel": "tours"})):
        plan = plan_links([dialog(user_id, sale_amount=5000.0,
                                  sale_currency="kgs", **broken)])
        kinds = {p.kind for p in plan.problems}
        assert AMOUNT_NEEDS_RECONCILIATION in kinds, f"сумма потеряна при {broken}"
        assert plan.links == ()


@pytest.mark.parametrize("amount", ["1 500", "1,5", True, -300.0, 1e22])
def test_ac07_unparseable_amounts_go_to_the_registry_not_to_silence(amount):
    """Непустая, но неразобранная сумма — строка реестра, а не тишина."""
    plan = plan_links([dialog("tours_bot:996700111222", funnel="tours",
                              sale_amount=amount)])
    assert [p.kind for p in plan.problems] == [AMOUNT_UNPARSEABLE]


def test_short_identity_is_not_inflated_into_a_phone_number():
    """Telegram-id из 9 цифр не достраивается до номера и не склеивается с людьми."""
    plan = plan_links([
        dialog("tg:700111222", funnel="tours"),
        dialog("w:996700111222", funnel="tours"),
    ])
    assert [link.legacy_user_ids for link in plan.links] == [("w:996700111222",)]
    assert [p.kind for p in plan.problems] == [UNNORMALIZABLE_PHONE]


def test_link_carries_no_money_fields_at_all():
    """AC-07 структурно: в связи нет ни одного денежного поля."""
    names = {f.name for f in dataclasses.fields(Link)}
    assert names == {"phone", "direction", "legacy_user_ids", "bitrix_lead_ids",
                     "outcomes"}
    assert not {n for n in names if "amount" in n or "sale" in n or "currency" in n}


def test_every_dialog_lands_either_in_a_link_or_in_the_registry():
    """Баланс: ни одно обращение не теряется молча."""
    dialogs = [
        dialog("tours_bot:996700111222", funnel="tours"),
        dialog("visa_bot:996555333444", funnel="visa"),
        dialog("tours_bot:bad", phone="нет", funnel="tours"),
        dialog("tours_bot:996700999888", funnel=None),
        LegacyDialog(user_id="w:996700111222", phone="996555333444", funnel="tours"),
    ]
    plan = plan_links(dialogs)
    accounted = {uid for link in plan.links for uid in link.legacy_user_ids}
    accounted |= {uid for problem in plan.problems for uid in problem.user_ids}
    assert accounted == {d.user_id for d in dialogs}


def test_mixed_card_detail_reports_both_numbers_and_dialogs():
    """В спорной строке видно и число номеров, и число затронутых обращений."""
    plan = plan_links([
        dialog("tours_bot:996700111222", funnel="tours", bitrix_lead_id="777"),
        dialog("sezim:996700111222", funnel="tours", bitrix_lead_id="777"),
        dialog("tours_bot:996555333444", funnel="tours", bitrix_lead_id="777"),
    ])
    mixed = [p for p in plan.problems if p.kind == MIXED_BITRIX_CARD][0]
    assert "2 разных номеров" in mixed.detail and "3 обращений" in mixed.detail
    assert len(mixed.user_ids) == 3
