"""ГЕЙТ: оверлей подтверждений — что боту РАЗРЕШЕНО произносить и что по-прежнему нет.

Написан ДО оверлея и до правок движка.

Зачем отдельный гейт. Оверлей `knowledge/kg_entry/confirmations-v1.1.yaml` — это
единственный файл в проекте, который превращает черновую выписку из ТЗ в норму, которую
бот произносит иностранцу как факт. Ошибка здесь не ломает тест и не падает в логах: она
выглядит как уверенный неверный ответ про закон Кыргызстана.

Основание для подтверждений: Гриша (заказчик по визам) 22.10.2026 через Алана разрешил
«чтобы как в пдф было». Разрешение владельца — не доказательство совпадения данных с
источником, поэтому совпадение проверяется машинно:
`python scripts/verify_entry_confirmations.py` сам разбирает таблицы 2.3 и 2.10 из PDF и
сличает их с бандлом.

Что здесь закреплено:

1. **Подтверждено ровно то, что сверено, и ничего больше.** Состав оверлея прибит
   числами по видам единиц. Новая строка в оверлее обязана ронять этот тест.
2. **Метка ТЗ сильнее подтверждения.** `[ПРОВЕРИТЬ]` (`verify`) и `[РЕШЕНИЕ]`
   (`decision`) не произносятся даже после подтверждения человеком.
3. **Цены не подтверждаются вообще** — решение Алана 21.10.2026: бот сумм не называет,
   потому что в ТЗ (прил. Г п.2) государственные сборы имеют статус «Открыт».
4. **Правка значения аннулирует подтверждение**, а несовпадение контрольной суммы
   бандла аннулирует оверлей целиком.
5. **Пробел по Молдове не превращается в ответ.** ТЗ относит её к странам вне Перечня,
   в данных этого нет — значит срок регистрации для MDA уходит менеджеру, а не клиенту.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knowledge" / "kg_entry" / "confirmations-v1.1.yaml"
BUNDLE = ROOT / "knowledge" / "kg_entry" / "draft-v1.1"

# Прибито 21.10.2026, те же числа, что в tests/test_entry_bundle_pinned.py.
PINNED_BUNDLE_HASH = "bf9faa537ae600c433a064ab21b8d5969aa63ba99fc39ead224dc6fa5256dea5"
PINNED_SOURCE_HASH = "141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2"

# Состав подтверждений 22.10.2026. Сверено скриптом verify_entry_confirmations.py:
# 92 страны освобождения из таблицы 2.10, пять безвизовых режимов минус помеченный
# меткой `verify`, три визовых порядка, общий срок учёта и два срока оформления.
EXPECTED_KINDS = {
    "registration_exemption": 92,
    "registration_default": 1,
    "registration_term": 2,
    "visa_free_regime": 4,
    "visa_required_regime": 3,
}
EXPECTED_TOTAL = sum(EXPECTED_KINDS.values())


@pytest.fixture(scope="module")
def engine():
    pytest.importorskip("app.knowledge.entry_regime")
    from app.knowledge import entry_regime
    if not entry_regime.available():
        pytest.skip("бандл знаний недоступен в этом дереве")
    return entry_regime


@pytest.fixture(scope="module")
def units(engine) -> dict[str, dict]:
    """Единицы в том виде, в каком их видит движок.

    Именно загруженный бандл, а не сырой units.yaml: загрузчик нормализует значения
    (сортирует списки стран), и подтверждение сверяется с нормализованной формой.
    """
    from app.knowledge.entry_bundle import loaded
    bundle = loaded()
    assert bundle is not None
    return {u["unit_id"]: u for u in bundle.units}


@pytest.fixture(scope="module")
def overlay() -> dict:
    if not OVERLAY.exists():
        pytest.fail("нет knowledge/kg_entry/confirmations-v1.1.yaml — "
                    "подтверждать единицы знаний нечем")
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


def _ask(engine, country, **kw):
    iso = engine.resolve_citizenship(country)
    assert iso is not None, f"не распознана страна {country!r}"
    return engine.evaluate(engine.EntryQuery(citizenship_iso3=iso, **kw))


# --- A. Состав и происхождение оверлея -----------------------------------------

def test_overlay_is_pinned_to_this_bundle_and_this_pdf(overlay):
    from app.knowledge import entry_confirmations
    assert overlay.get("schema_version") == entry_confirmations.SCHEMA_VERSION
    assert overlay.get("bundle_hash") == PINNED_BUNDLE_HASH, \
        "оверлей подтверждает не тот бандл, на котором отвечает бот"
    assert overlay.get("source_hash") == PINNED_SOURCE_HASH, \
        "оверлей сверялся не с тем PDF"


def test_overlay_confirms_exactly_what_was_checked(overlay, units):
    rows = overlay.get("confirmed") or []
    assert len(rows) == EXPECTED_TOTAL, (
        f"в оверлее {len(rows)} подтверждений вместо {EXPECTED_TOTAL}. Каждая новая "
        "строка — это новая норма, которую бот начнёт утверждать: обнови числа "
        "осознанно и приложи прогон scripts/verify_entry_confirmations.py.")
    seen = [row["unit_id"] for row in rows]
    assert len(set(seen)) == len(seen), "в оверлее есть дубли"
    kinds: dict[str, int] = {}
    for uid in seen:
        assert uid in units, f"оверлей подтверждает несуществующую единицу {uid}"
        kind = units[uid]["kind"]
        kinds[kind] = kinds.get(kind, 0) + 1
    assert kinds == EXPECTED_KINDS


def test_every_row_carries_its_value_hash_and_who_approved_it(overlay, units):
    from app.knowledge import entry_confirmations
    for row in overlay.get("confirmed") or []:
        uid = row["unit_id"]
        unit = units[uid]
        assert unit["value"] is not None, f"{uid}: подтверждено пустое значение"
        assert row.get("value_sha256") == entry_confirmations.value_digest(unit["value"]), \
            f"{uid}: хеш значения не совпадает с бандлом"
        for field in ("basis", "approved_by", "checked_by", "confirmed_at"):
            assert row.get(field), f"{uid}: не записано {field}"
        assert row.get("source_ref"), f"{uid}: не записано основание из ТЗ"


def test_labelled_units_are_never_confirmed(overlay, units):
    """`[ПРОВЕРИТЬ]` и `[РЕШЕНИЕ]` — сам ТЗ считает это непроверенным."""
    for row in overlay.get("confirmed") or []:
        label = units[row["unit_id"]].get("label")
        assert label not in ("verify", "decision"), \
            f"{row['unit_id']}: подтверждена единица с меткой {label!r}"


def test_no_price_is_ever_confirmed(overlay, units):
    """Решение Алана: бот сумм не называет. В ТЗ госсборы имеют статус «Открыт»."""
    for row in overlay.get("confirmed") or []:
        kind = units[row["unit_id"]]["kind"]
        assert kind != "tariff", f"{row['unit_id']}: подтверждён тариф — бот назовёт цену"


# --- B. Что боту теперь разрешено сказать ---------------------------------------

@pytest.mark.parametrize("country,days,window", [
    ("Россия", 90, 180), ("Казахстан", 90, 180), ("Турция", 90, 180),
    ("Узбекистан", 60, 120), ("Австрия", 30, 60), ("США", 30, 60),
])
def test_visa_free_regime_and_limit_are_now_sayable(engine, country, days, window):
    v = _ask(engine, country)
    assert v.regime == "visa_free"
    assert (v.stay_limit_days, v.window_days) == (days, window)
    assert {"regime", "stay_limit"} <= v.sayable, (
        f"{country}: режим и лимит подтверждены, но бот их не произносит — {v.sayable}")


@pytest.mark.parametrize("country", ["Нигерия", "Афганистан", "Китай"])
def test_visa_required_regime_is_now_sayable(engine, country):
    v = _ask(engine, country)
    assert v.regime == "visa_required"
    assert "regime" in v.sayable, f"{country}: визовый порядок подтверждён, но молчит"


@pytest.mark.parametrize("country,exempt", [("США", 30), ("Австрия", 30), ("Сербия", 60)])
def test_registration_exemption_is_now_sayable(engine, country, exempt):
    v = _ask(engine, country)
    assert v.registration is not None and v.registration.exempt_days == exempt
    assert "registration" in v.sayable, f"{country}: срок освобождения всё ещё не говорим"


def test_b8_case_3_uzbek_worker_can_now_hear_the_rule(engine):
    """Эталон Б.8 №3: 60/120, нужно ЕР, учёт за 5 рабочих дней, регистрация на 60 дней."""
    v = _ask(engine, "Узбекистан", purpose="work_hire", location="in_kg")
    assert (v.stay_limit_days, v.window_days) == (60, 120)
    assert v.unified_permit_required is True
    assert v.registration.working_days_from_border == 5
    assert v.registration.registered_for_days == 60
    assert {"regime", "stay_limit", "unified_permit", "registration"} <= v.sayable


def test_every_sayable_verdict_carries_its_source(engine):
    """Б.2 п.4: каждый вывод с коротким основанием. Иначе произносить нельзя."""
    for country in ("Россия", "США", "Узбекистан", "Нигерия"):
        v = _ask(engine, country)
        if not v.sayable:
            continue
        assert v.units and all(u.source_ref and u.page for u in v.units), \
            f"{country}: разрешено говорить факт без ссылки на источник"


# --- C. Что молчит и после подтверждения ----------------------------------------

@pytest.mark.parametrize("country", ["Таджикистан", "Азербайджан", "Грузия"])
def test_cis_bilateral_still_cannot_be_spoken(engine, country):
    """60/120 известно «по сообщениям СМИ» — ТЗ помечает это `[ПРОВЕРИТЬ]`."""
    v = _ask(engine, country)
    assert "stay_limit" not in v.sayable and "regime" not in v.sayable, \
        f"{country}: произнесён факт с меткой verify"


def test_moldova_registration_is_never_spoken(engine):
    """Пробел импорта: ТЗ относит Молдову к странам вне Перечня, в данных этого нет."""
    v = _ask(engine, "Молдова")
    assert "registration" not in v.sayable, \
        "срок регистрации для Молдовы произнесён, хотя данных по ней нет"
    assert any("registration" in w for w in v.withheld)


@pytest.mark.parametrize("doc", ["diplomatic", "service", "stateless", "refugee", "un_lp"])
def test_unusual_passports_stay_with_a_human(engine, doc):
    v = _ask(engine, "Россия", document_type=doc)
    assert v.sayable == frozenset()


def test_exact_remaining_days_are_still_never_sayable(engine):
    v = _ask(engine, "Россия", entry_on="2026-11-01", exit_on="2026-11-20",
             history=(("2026-08-01", "2026-08-20"),))
    assert "remaining_days" not in v.sayable
    assert not {f for f in v.sayable} - set(engine.FIELDS), \
        "в разрешённых полях появилось что-то вне белого списка FIELDS"


def test_registration_term_must_be_confirmed_on_its_own(engine, monkeypatch):
    """Срок, НА КОТОРЫЙ оформляется регистрация, — отдельная единица знаний.

    Подтверждение общего срока учёта не разрешает произносить ещё и его: иначе бот
    озвучит число из неподтверждённой единицы.
    """
    from app.knowledge import entry_confirmations
    real = entry_confirmations.confirmed
    monkeypatch.setattr(entry_confirmations, "confirmed",
                        lambda unit: unit.get("kind") != "registration_term" and real(unit))
    v = _ask(engine, "Узбекистан", purpose="work_hire")
    assert v.registration.registered_for_days == 60, "значение для менеджера пропало"
    assert "registration" not in v.sayable, \
        "срок оформления регистрации произнесён без подтверждения своей единицы"


# --- C2. Страны, которым по ТЗ виза НЕ нужна, а в данных это не выражено --------

# Таблица 2.2 ТЗ, строки «Нужна ли виза = Нет», которые бандл не смог выразить:
# у единиц `KG.VF.GCC`, `MDV`, `MYS`, `CUB`, `PRK` и `KG.SP.HK_MACAO` пустое значение
# и потерян список стран, поэтому индекс не привязывает к ним гражданство.
PDF_VISA_FREE_BUT_UNEXPRESSED = {
    # ССАГПЗ, с. 21: «Нет, 180 дней в каждом 360-дневном периоде»
    "Саудовская Аравия": "SAU", "ОАЭ": "ARE", "Катар": "QAT",
    "Кувейт": "KWT", "Оман": "OMN", "Бахрейн": "BHR",
    # с. 21: 30 дней
    "Мальдивы": "MDV", "Гонконг": "HKG", "Макао": "MAC", "Малайзия": "MYS",
    # с. 21: срок в источниках не найден, ТЗ предписывает эскалацию
    "Куба": "CUB", "КНДР": "PRK",
}


@pytest.mark.parametrize("country", sorted(PDF_VISA_FREE_BUT_UNEXPRESSED))
def test_countries_the_pdf_calls_visa_free_never_hear_a_visa_requirement(engine, country):
    """Худший из возможных неверных ответов: «нужна виза» тому, кому она не нужна.

    Движок проваливал такие страны в единицу «все остальные» (общий порядок плюс
    согласование ГКНБ). Она подтверждена, поэтому бот утверждал бы это как факт, а
    клиент из ОАЭ купил бы визу, которая ему не нужна.
    """
    v = _ask(engine, country, purpose="tourism")
    assert "regime" not in v.sayable, (
        f"{country}: бот утверждает режим въезда, хотя ТЗ относит страну к безвизовым, "
        f"а данные этого не выражают (получено {v.regime!r})")
    assert any("regime" in w for w in v.withheld), \
        f"{country}: причина умолчания о режиме не записана для менеджера"


@pytest.mark.parametrize("country", ["Мальдивы", "Малайзия", "Куба", "КНДР"])
def test_an_empty_visa_free_unit_does_not_become_the_general_procedure(engine, country):
    """У этих стран безвизовая единица привязана, но пустая.

    Пустое значение — это «мы не знаем срок», а не «безвиза нет». Подмена пустой
    единицы единицей «все остальные» заодно обходила метку `verify`.
    """
    v = _ask(engine, country, purpose="tourism")
    assert v.regime != "visa_required", \
        f"{country}: пустая безвизовая единица подменена общим визовым порядком"
    assert v.sayable == frozenset(), f"{country}: произносится вывод по пустой единице"


@pytest.mark.parametrize("citizenship", ["Кыргызстан", "KGZ", "ESH"])
def test_no_entry_verdict_for_citizenships_that_have_no_entry_rule(engine, citizenship):
    """Гражданину КР виза в КР не нужна — такой строки в таблице 2.2 нет и быть не может.

    Движок проваливал его в единицу «все остальные», и бот утверждал «нужна виза с
    согласованием ГКНБ» гражданину Кыргызстана. Туда же непризнанные паспорта: ТЗ,
    ШАГ 2 — эскалация со словами «оформить нельзя».
    """
    v = _ask(engine, citizenship, purpose="tourism")
    assert v.sayable == frozenset(), f"{citizenship}: произносится вывод о режиме"
    assert any("no_entry_rule_for_citizenship" in w for w in v.withheld)


@pytest.mark.parametrize("country", ["Нигерия", "Афганистан", "Китай", "Туркменистан"])
def test_the_general_procedure_still_answers_where_the_pdf_puts_it(engine, country):
    """Обратная сторона: «все остальные» — верный ответ для этих стран (ТЗ 2.2, с. 22).

    Страховка не должна заглушить самую большую группу визовых стран.
    """
    v = _ask(engine, country, purpose="tourism")
    assert v.regime == "visa_required"
    assert v.gknb_approval is True
    assert "regime" in v.sayable, f"{country}: верный ответ про визу перестал звучать"


# --- D. Аннулирование подтверждения --------------------------------------------

def test_editing_a_value_kills_its_confirmation(units):
    """Правка значения в бандле обязана аннулировать подтверждение этой единицы."""
    from app.knowledge import entry_confirmations
    entry_confirmations.reset()
    unit = dict(units["KG.VF.EAEU"])
    assert entry_confirmations.confirmed(unit), "исходное значение не подтверждено"
    tampered = dict(unit)
    tampered["value"] = dict(unit["value"], days=120)
    assert not entry_confirmations.confirmed(tampered), \
        "подтверждение выжило правку значения — устаревшее правило уедет клиенту"


def test_wrong_bundle_hash_voids_the_whole_overlay(units, monkeypatch):
    from app.knowledge import entry_confirmations
    entry_confirmations.reset()
    real = entry_confirmations.load()
    assert real is not None
    monkeypatch.setattr(entry_confirmations, "load",
                        lambda: entry_confirmations.Confirmations(
                            bundle_hash="0" * 64, source_hash=real.source_hash,
                            by_unit=real.by_unit))
    assert not entry_confirmations.confirmed(dict(units["KG.VF.EAEU"])), \
        "оверлей от другого бандла всё ещё действует"


@pytest.mark.parametrize("bundle_hash,source_hash,case", [
    ("", None, "пустой bundle_hash"),
    (None, "z" * 64, "чужой source_hash"),
    ("", "", "оба пустые"),
])
def test_a_confirmation_without_a_real_binding_is_not_trusted(
        units, monkeypatch, bundle_hash, source_hash, case):
    """Привязка оверлея к бандлу и к PDF обязательна, а не «если указана».

    Хеш значения защищает от правки значения, но не от добавления, удаления или
    переименования единиц. От этого защищает только привязка к бандлу целиком —
    значит пустая привязка не может считаться привязкой.
    """
    from app.knowledge import entry_confirmations
    entry_confirmations.reset()
    real = entry_confirmations.load()
    assert real is not None
    patched = entry_confirmations.Confirmations(
        bundle_hash=real.bundle_hash if bundle_hash is None else bundle_hash,
        source_hash=real.source_hash if source_hash is None else source_hash,
        by_unit=real.by_unit)
    monkeypatch.setattr(entry_confirmations, "load", lambda: patched)
    assert not entry_confirmations.confirmed(dict(units["KG.VF.EAEU"])), \
        f"{case}: оверлей без настоящей привязки всё ещё действует"


def test_confirmed_units_on_real_data_match_the_selection_rule(units):
    """Инвариант по поставляемым данным, а не по механизму.

    Проверяет ровно то, что раньше проверял тест «оверлей пуст»: что в поставке
    подтверждено ровно ожидаемое и ни одной единицы больше. Правило повторяет
    scripts/build_entry_confirmations.py.
    """
    from app.knowledge import entry_confirmations
    entry_confirmations.reset()
    allowed_kinds = set(EXPECTED_KINDS)
    unexpected: list[str] = []
    missing: list[str] = []
    for uid, unit in units.items():
        eligible = (unit.get("kind") in allowed_kinds
                    and unit.get("value") is not None
                    and str(unit.get("label") or "") == "none"
                    and not unit.get("conflict_ref"))
        is_confirmed = entry_confirmations.confirmed(unit)
        if is_confirmed and not eligible:
            unexpected.append(uid)
        if eligible and not is_confirmed:
            missing.append(uid)
    assert unexpected == [], f"подтверждено лишнее: {unexpected}"
    assert missing == [], f"правило отбора выполнено, но подтверждения нет: {missing}"


def test_an_unconfirmed_unlabelled_rule_is_marked_for_the_manager(monkeypatch):
    """Путь `not_confirmed` обязан быть виден в карточке, а не только путь по метке."""
    from app.core import entry_card
    from app.knowledge import entry_confirmations
    from app.knowledge.entry_regime import EntryQuery, evaluate, resolve_citizenship

    monkeypatch.setattr(entry_confirmations, "confirmed", lambda unit: False)
    verdict = evaluate(EntryQuery(citizenship_iso3=resolve_citizenship("Россия")))
    card = entry_card.render({"name": "X", "phone": "996700000000"}, verdict)
    assert "not_confirmed" in card, "менеджер не видит, что правило не прошло приёмку"
    assert "не подтверждено" in card


# --- E. Остаток дней: запрет ТЗ 2.9 не зависит от подтверждений -----------------

@pytest.mark.parametrize("text", [
    "У вас осталось 12 дней пребывания.",
    "Остаток — 5 дней в текущем окне.",
    "Вы можете пробыть ещё 20 дней.",
    "В запасе 3 дня, лучше выехать раньше.",
    "You have 14 days left in this window.",
])
def test_remaining_days_are_blocked_even_when_the_limit_is_allowed(text):
    """Лимит из нормы произносить можно, остаток по конкретному человеку — никогда.

    Оба утверждения выглядят одинаково — «число рядом со словом день», — поэтому
    разрешение произносить лимит само по себе открывало дорогу остатку. ТЗ 2.9:
    остаток считает государственная система учёта, доступа к ней нет, политика
    подсчёта дня въезда и выезда в данных не подтверждена.
    """
    from app.agent.validator import validate_reply
    clean, violations = validate_reply(
        text, "visa", profile="kg_entry",
        allowed_claims=frozenset({"regime", "stay_limit", "registration",
                                  "unified_permit"}))
    assert "kg_entry_remaining_days_blocked" in violations
    assert clean != text, f"остаток дней дошёл до клиента: {clean!r}"


def test_a_neighbouring_word_is_not_mistaken_for_a_remainder():
    """«Остальное» — не «осталось». Ремень не должен подменять нормальную реплику."""
    from app.agent.validator import validate_reply
    text = "Документы готовим 3 дня, остальное обсудим на встрече."
    clean, violations = validate_reply(
        text, "visa", profile="kg_entry",
        allowed_claims=frozenset({"regime", "stay_limit"}))
    assert "kg_entry_remaining_days_blocked" not in violations
    assert clean == text


def test_the_limit_from_the_rule_still_passes():
    from app.agent.validator import validate_reply
    text = "Без визы можно находиться 30 дней в каждом 60-дневном периоде."
    clean, violations = validate_reply(
        text, "visa", profile="kg_entry",
        allowed_claims=frozenset({"regime", "stay_limit"}))
    assert "kg_entry_remaining_days_blocked" not in violations
    assert clean == text, "норма из ТЗ подменена вместе с остатком"


def test_only_sayable_facts_reach_the_model_context(engine):
    """В промпт кладём лишь разрешённое: что модель видит, она рано или поздно скажет."""
    from app.core.entry_card import sayable_regime_line

    tjk = _ask(engine, "Таджикистан")
    line = sayable_regime_line(tjk, tjk.sayable)
    assert "60/120" not in line, \
        "лимит с меткой verify попал в контекст модели — остался один рубеж из двух"

    rus = _ask(engine, "Россия")
    # Окно раскрыто словами, а не дробью — см. test_the_window_is_spelled_out_for_the_model.
    assert "90 дней в каждые 180" in sayable_regime_line(rus, rus.sayable)
    # Тумблер речи выключен — в контекст не уходит ни одного числа.
    silent = sayable_regime_line(rus, frozenset())
    assert "90" not in silent and "180" not in silent
    assert "специалист" in silent


# --- F. Реплика обязана остаться читаемой --------------------------------------
# Всё в этом разделе найдено живым прогоном в Telegram 22.10, не тестами: прежние
# тесты проверяли, что запрещённое НЕ дошло до клиента, и ни один не проверял, что
# дошедшее можно прочитать.

def test_cutting_a_claim_keeps_the_punctuation_of_the_rest():
    """Ремень убирает предложение, а не знаки препинания у соседних.

    Ветка неподтверждённых утверждений собирала только ТЕЛА предложений и склеивала
    их пробелами, теряя точки, вопросительные и восклицательные знаки по всей реплике.
    Клиент видел «Hi I am Medina Great question When do you plan to arrive» — так бот
    выглядит сломанным, и заодно ломается подсчёт вопросов в реплике.
    """
    from app.agent.validator import validate_reply
    text = ("Hi! I am Medina. Great question! You do not need a visa for 30 days. "
            "When do you plan to arrive?")
    clean, violations = validate_reply(text, "visa", profile="kg_entry",
                                       allowed_claims=frozenset())
    assert "kg_entry_unconfirmed_claim_blocked" in violations
    assert "You do not need a visa" not in clean, "неподтверждённое правило дошло"
    assert "Hi! I am Medina." in clean, f"потеряна пунктуация: {clean!r}"
    assert "Great question!" in clean
    assert "When do you plan to arrive?" in clean


def test_the_safe_replacement_speaks_the_language_of_the_reply():
    """Английскому клиенту нельзя отвечать русской вставкой.

    В прогоне бот писал «…are you traveling alone Это правило уточнит специалист»:
    безопасные подмены существовали только по-русски.
    """
    from app.agent.validator import validate_reply
    english = ("Hello! You do not need a visa for 30 days. "
               "When are you planning to arrive?")
    clean, _ = validate_reply(english, "visa", profile="kg_entry",
                              allowed_claims=frozenset())
    assert not any("а" <= ch.lower() <= "я" for ch in clean), \
        f"в английский ответ попала кириллица: {clean!r}"
    assert "specialist" in clean.lower()

    russian = "Здравствуйте! Виза вам не нужна 30 дней. Когда планируете приехать?"
    clean_ru, _ = validate_reply(russian, "visa", profile="kg_entry",
                                 allowed_claims=frozenset())
    assert "специалист" in clean_ru.lower(), "русский ответ получил английскую вставку"


@pytest.mark.parametrize("text", [
    "You can work a little on a tourist visa, nobody checks.",
    "Registration will extend your visa-free stay.",
    "You can just pay the fine at the airport when you leave.",
    "We will extend your tourist visa later, no problem.",
    "We can speed it up through our contacts.",
    "You can stay in the country while your application is pending.",
])
def test_appendix_b7_belts_also_work_in_english(text):
    """Аудитория въездной ветки — иностранцы, половина пишет по-английски.

    Шесть запретов Б.7 были написаны только по-русски, то есть англоязычному клиенту
    бот мог пообещать что угодно. Поймано живым прогоном 22.10: «We guarantee your
    visa will be approved» не ловилось ничем.
    """
    from app.agent.validator import validate_reply
    clean, violations = validate_reply(text, "visa", profile="kg_entry",
                                       allowed_claims=frozenset({"regime", "stay_limit",
                                                                 "registration",
                                                                 "unified_permit"}))
    assert any(v.startswith("kg_entry_forbidden_") for v in violations), \
        f"запрещённая формулировка прошла по-английски: {text!r} -> {violations}"
    assert clean != text


@pytest.mark.parametrize("text", [
    # Так модель ответила американцу в живом прогоне 22.10. По ТЗ 30/60 — это «30 дней
    # в каждом 60-дневном периоде», а не «30 плюс регистрация = 60». Регистрация
    # безвизовый срок НЕ продлевает (Б.7 и правило 2.9), но прежний шаблон ловил только
    # слова «продлить» и «extend», а этой формулировки в нём нет.
    "You get 30 days visa-free, and if you register you can stay up to 60 days total.",
    "Register with the authorities and you can remain for 60 days in total.",
    "Если зарегистрируетесь, сможете остаться до 60 дней.",
    "С регистрацией вы сможете пробыть дольше — до 60 дней.",
])
def test_registration_never_buys_extra_days(text):
    """Самый дорогой неверный ответ: человек останется дольше и получит запрет на въезд."""
    from app.agent.validator import validate_reply
    clean, violations = validate_reply(text, "visa", profile="kg_entry",
                                       allowed_claims=frozenset({"regime", "stay_limit",
                                                                 "registration",
                                                                 "unified_permit"}))
    assert "kg_entry_forbidden_registration_extends" in violations, \
        f"бот обещал лишние дни за регистрацию: {text!r} -> {violations}"
    assert clean != text


def test_the_window_is_spelled_out_for_the_model():
    """Модели нельзя давать «30/60»: она читает это как сумму, а не как окно.

    В живом прогоне она превратила «30/60» в «30 дней плюс регистрация = 60 дней».
    """
    from app.core.entry_card import sayable_regime_line
    from app.knowledge.entry_regime import EntryQuery, evaluate, resolve_citizenship
    v = evaluate(EntryQuery(citizenship_iso3=resolve_citizenship("США"),
                            purpose="tourism"))
    line = sayable_regime_line(v, v.sayable)
    assert "30/60" not in line, f"в контекст модели ушла дробь: {line!r}"
    assert "30 дней в каждые 60" in line or "30 дней в каждом 60" in line, \
        f"окно не раскрыто словами: {line!r}"


@pytest.mark.parametrize("text", [
    "You may not work on a tourist visa without a permit.",
    "Registration does not extend your visa-free period.",
    "A tourist visa cannot be extended.",
])
def test_the_correct_english_wording_is_not_blocked(text):
    """Правильный ответ содержит те же слова с отрицанием — его блокировать нельзя."""
    from app.agent.validator import validate_reply
    clean, violations = validate_reply(text, "visa", profile="kg_entry",
                                       allowed_claims=frozenset({"regime", "stay_limit",
                                                                 "registration",
                                                                 "unified_permit"}))
    assert not any(v.startswith("kg_entry_forbidden_") for v in violations), \
        f"верная формулировка заблокирована: {text!r} -> {violations}"
    assert clean == text


@pytest.mark.parametrize("text,marker", [
    ("The service fee is $50 per person.", "specialist"),
    ("The service costs 50 dollars per person.", "specialist"),
    ("We guarantee your visa will be approved.", "decision"),
    ("Approval is 100% guaranteed.", "decision"),
    ("You have 12 days left.", "stamps"),
])
def test_english_belts_replace_with_english_text(text, marker):
    from app.agent.validator import validate_reply
    clean, violations = validate_reply(text, "visa", profile="kg_entry",
                                       allowed_claims=frozenset({"regime", "stay_limit",
                                                                 "registration",
                                                                 "unified_permit"}))
    assert violations, f"ремень не сработал на {text!r}"
    assert not any("а" <= ch.lower() <= "я" for ch in clean), \
        f"кириллица в английской подмене: {clean!r}"
    assert marker in clean.lower(), f"ожидал {marker!r} в подмене: {clean!r}"


def test_missing_overlay_means_nothing_is_sayable(engine, monkeypatch):
    """Удаление оверлея — штатный откат: бот возвращается к «уточнит специалист»."""
    from app.knowledge import entry_confirmations
    monkeypatch.setattr(entry_confirmations, "load", lambda: None)
    for country in ("Россия", "США", "Узбекистан", "Нигерия"):
        v = _ask(engine, country)
        assert v.sayable == frozenset(), f"{country}: без оверлея бот всё равно утверждает"
        assert v.withheld
