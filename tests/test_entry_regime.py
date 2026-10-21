"""ГЕЙТ: движок режима въезда в Кыргызстан.

Написан ДО реализации и исполнителем НЕ редактируется.

ТЗ (с. 2, таблица «что куда загружать») требует, чтобы режим въезда проверялся **кодом**,
а не моделью: «JSON Б.3 и YAML Б.5 — в код и настройки, а не в поиск». Поэтому движок —
чистая функция без БД и без LLM, и всё, что он утверждает, выводится из единиц знаний
с указанием основания.

Ожидания ниже сверены с фактическими данными бандла 21.10.2026, а не придуманы.

Три запрета, которые здесь закреплены, потому что их нарушение стоит дороже всего:

1. **Неподтверждённое нельзя произносить.** Пока оверлей подтверждений пуст, `sayable`
   пуст у любого запроса. Бот при этом не молчит — он передаёт менеджеру.
2. **Точный остаток дней клиенту не называется никогда.** ТЗ 2.9 прямо запрещает
   «обещать остаток по расчёту в уме», политика подсчёта дней в данных не подтверждена.
3. **Особый режим и необычный паспорт — всегда человек.** Все четыре единицы
   `special_regime` имеют пустое значение, а дипломатический паспорт — стоп-фактор 4.1.
"""
import pytest


@pytest.fixture(scope="module")
def engine():
    pytest.importorskip("app.knowledge.entry_regime")
    from app.knowledge import entry_regime
    if not entry_regime.available():
        pytest.skip("бандл знаний недоступен в этом дереве")
    return entry_regime


def _ask(engine, country, **kw):
    iso = engine.resolve_citizenship(country)
    assert iso is not None, f"не распознана страна {country!r}"
    return engine.evaluate(engine.EntryQuery(citizenship_iso3=iso, **kw))


# --- A. Безвизовые режимы: лимит и окно ----------------------------------------

@pytest.mark.parametrize("country,days,window,permit", [
    ("Россия", 90, 180, False),          # ЕАЭС: работать можно без Единого разрешения
    ("Казахстан", 90, 180, False),
    ("Турция", 90, 180, True),           # 90/180, но для работы нужно ЕР
    ("Узбекистан", 60, 120, True),
    ("Австрия", 30, 60, True),           # приложение 1
    ("Германия", 30, 60, True),
])
def test_visa_free_limits(engine, country, days, window, permit):
    v = _ask(engine, country)
    assert v.regime == "visa_free", f"{country}: ожидался безвиз, получено {v.regime}"
    assert (v.stay_limit_days, v.window_days) == (days, window)
    assert v.unified_permit_required is permit
    # Основание обязательно: Б.2 п.4 «каждый вывод с коротким основанием».
    assert v.units and all(u.source_ref for u in v.units)


# --- B. Визовые режимы ---------------------------------------------------------

@pytest.mark.parametrize("country", ["Нигерия", "Афганистан", "Китай"])
def test_other_countries_need_a_visa_in_the_general_procedure(engine, country):
    v = _ask(engine, country)
    assert v.regime == "visa_required"
    assert any(u.unit_id == "KG.VR.GENERAL" for u in v.units)
    assert v.stay_limit_days is None, "у визового режима нет безвизового лимита"


def test_simplified_procedure_countries(engine):
    v = _ask(engine, "Индонезия")
    assert v.regime == "visa_required"
    assert any(u.unit_id == "KG.VR.SIMPLIFIED_ALL" for u in v.units)


def test_iran_simplified_only_for_business_and_tourism(engine):
    """У Ирана упрощённый порядок ограничен целью — scope `business_tourist`."""
    tourism = _ask(engine, "Иран", purpose="tourism")
    assert any(u.unit_id == "KG.VR.SIMPLIFIED_IRN_B_TS" for u in tourism.units)
    work = _ask(engine, "Иран", purpose="work_hire")
    assert work.regime in ("visa_required", "unknown")
    assert not any(u.unit_id == "KG.VR.SIMPLIFIED_IRN_B_TS" for u in work.units), \
        "упрощённый порядок применён к цели вне его scope"


# --- C. Регистрация ------------------------------------------------------------

@pytest.mark.parametrize("country,exempt_days", [
    ("Россия", 30), ("Турция", 90), ("Греция", 90), ("Чили", 60),
    ("Сербия", 60), ("Монголия", 30), ("Иран", 8),
])
def test_registration_exemption_days(engine, country, exempt_days):
    """Источник истины — таблица 2.10 (93 страны), а не беднейший YAML Б.5."""
    v = _ask(engine, country)
    assert v.registration is not None, f"{country}: срок регистрации не определён"
    assert v.registration.exempt_days == exempt_days


@pytest.mark.parametrize("country", ["Узбекистан", "Китай", "Нигерия", "Пакистан"])
def test_countries_without_exemption_register_in_five_working_days(engine, country):
    v = _ask(engine, country)
    assert v.registration is not None
    assert v.registration.exempt_days is None
    assert v.registration.working_days_from_border == 5


def test_moldova_registration_stays_unknown(engine):
    """ТЗ противоречит сам себе по Молдове — движок не выбирает сторону."""
    v = _ask(engine, "Молдова")
    assert v.regime == "visa_free" and v.stay_limit_days == 90
    assert v.registration is None or v.registration.exempt_days is None
    assert any("registration" in w for w in v.withheld), \
        "пробел по регистрации Молдовы не отмечен в withheld"


# --- D. Передача человеку ------------------------------------------------------

@pytest.mark.parametrize("doc", ["diplomatic", "service", "stateless", "refugee", "un_lp"])
def test_unusual_passports_go_to_a_human(engine, doc):
    """Стоп-фактор 4.1: по таким документам бот не консультирует по существу."""
    v = _ask(engine, "Россия", document_type=doc)
    assert v.regime == "unknown"
    assert v.sayable == frozenset()
    assert any("document" in w for w in v.withheld)


def test_unknown_country_is_not_guessed(engine):
    assert engine.resolve_citizenship("Нарния") is None
    assert engine.resolve_citizenship("") is None


# --- E. Английские названия: иностранец пишет не по-русски ----------------------

@pytest.mark.parametrize("name,iso3", [
    ("India", "IND"), ("india", "IND"), ("China", "CHN"), ("Uzbekistan", "UZB"),
    ("Russia", "RUS"), ("Turkey", "TUR"), ("Germany", "DEU"), ("Pakistan", "PAK"),
    ("United Kingdom", "GBR"), ("USA", "USA"), ("IND", "IND"),
])
def test_english_country_names_resolve(engine, name, iso3):
    """Приёмка — иностранец в WhatsApp. Без этого ядро падает на первом шаге."""
    assert engine.resolve_citizenship(name) == iso3


def test_russian_names_still_resolve(engine):
    for name, iso3 in (("Индия", "IND"), ("Россия", "RUS"), ("Узбекистан", "UZB")):
        assert engine.resolve_citizenship(name) == iso3


# --- F. Что говорить нельзя ----------------------------------------------------

def test_nothing_is_sayable_while_the_overlay_is_empty(engine):
    """Главный предохранитель: 0 подтверждённых единиц ⇒ бот ничего не утверждает."""
    for country in ("Россия", "Турция", "Австрия", "Нигерия", "Узбекистан"):
        v = _ask(engine, country)
        assert v.sayable == frozenset(), (
            f"{country}: бот собрался произнести неподтверждённое правило — {v.sayable}")
        assert v.withheld, "причина умолчания не записана"


def test_cis_bilateral_is_never_sayable_even_if_confirmed(engine, monkeypatch):
    """Метка `verify` сильнее подтверждения: 60/120 по этим странам — только менеджер."""
    from app.knowledge import entry_confirmations
    monkeypatch.setattr(entry_confirmations, "confirmed", lambda unit: True)
    for country in ("Таджикистан", "Азербайджан", "Грузия"):
        v = _ask(engine, country)
        assert "stay_limit" not in v.sayable and "regime" not in v.sayable, \
            f"{country}: произнесён факт с меткой verify"


def test_exact_remaining_days_are_never_sayable(engine, monkeypatch):
    """ТЗ 2.9: «точный остаток дней клиенту не обещать по расчёту в уме»."""
    from app.knowledge import entry_confirmations
    monkeypatch.setattr(entry_confirmations, "confirmed", lambda unit: True)
    v = _ask(engine, "Россия", entry_on="2026-11-01", exit_on="2026-11-20",
             history=(("2026-08-01", "2026-08-20"),))
    assert "remaining_days" not in v.sayable
    assert "exact_remaining_days" not in v.sayable


def test_confirmed_units_unlock_their_own_field_only(engine, monkeypatch):
    """Подтверждение приходит неравномерно: режим можно, а регистрацию ещё нет."""
    from app.knowledge import entry_confirmations
    monkeypatch.setattr(entry_confirmations, "confirmed",
                        lambda unit: unit.get("kind") == "visa_free_regime")
    v = _ask(engine, "Россия")
    assert "regime" in v.sayable and "stay_limit" in v.sayable
    assert "registration" not in v.sayable, \
        "срок регистрации произнесён, хотя его единица не подтверждена"
